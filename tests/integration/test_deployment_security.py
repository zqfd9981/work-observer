"""单用户部署边界使用本地ASGI测试客户端与合成口令，不访问公网。"""

import re

import pytest
from starlette.testclient import TestClient

from work_observer.api.security import DeploymentGuard, deployment_settings
from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.database import upgrade

ACCESS = "synthetic-access-token-0123456789abcdef"
ORIGIN = "https://observer.example"


@pytest.fixture
def deployed(tmp_path):
    database = tmp_path / "deployed.db"
    upgrade(database)
    settings = Settings(
        database_path=database,
        raw_directory=tmp_path / "raw",
        access_token=ACCESS,
        public_origin=ORIGIN,
        model_api_key="synthetic-model-secret",
    )
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url=ORIGIN
    ) as client:
        yield client, settings


def jd():
    return {
        "title": "合成安全测试岗位",
        "company": "合成公司",
        "description": "合成原文。",
        "data_kind": "synthetic",
    }


@pytest.mark.parametrize(
    "options,code",
    [
        ({"public_origin": ORIGIN}, "DEPLOYMENT_ACCESS_CONFIG_REQUIRED"),
        ({"access_token": ACCESS}, "DEPLOYMENT_ACCESS_CONFIG_REQUIRED"),
        ({"public_origin": ORIGIN, "access_token": "short"}, "DEPLOYMENT_ACCESS_CONFIG_REQUIRED"),
        (
            {"public_origin": "http://observer.example", "access_token": ACCESS},
            "DEPLOYMENT_HTTPS_REQUIRED",
        ),
        (
            {"public_origin": ORIGIN + "/sub", "access_token": ACCESS},
            "DEPLOYMENT_ORIGIN_MUST_BE_ROOT",
        ),
        (
            {"public_origin": ORIGIN, "access_token": "合成" * 32},
            "DEPLOYMENT_ACCESS_CONFIG_REQUIRED",
        ),
    ],
)
def test_invalid_deployment_configuration_fails_before_serving(options, code):
    with pytest.raises(ProbeError, match=code):
        create_app(Settings(**options))


def test_default_local_mode_and_loopback_http_debug_are_explicit():
    assert deployment_settings(Settings()) is None
    for origin in ("http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"):
        assert deployment_settings(Settings(public_origin=origin, access_token=ACCESS)) == (
            origin,
            ACCESS,
        )


def test_anonymous_routes_and_login_html_never_contain_secrets(deployed):
    client, _ = deployed
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/assets/app.js", follow_redirects=False).status_code == 303
    html = client.get("/login")
    assert html.status_code == 200 and html.headers["cache-control"] == "no-store"
    assert ACCESS not in html.text and "synthetic-model-secret" not in html.text
    assert "frame-ancestors 'none'" in html.headers["content-security-policy"]


def test_cookie_login_requires_write_csrf_and_bearer_has_own_authentication(deployed):
    client, _ = deployed
    login = client.post("/login", data={"token": ACCESS}, follow_redirects=False)
    assert login.status_code == 303
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert ACCESS not in cookie
    html = client.get("/")
    assert ACCESS not in html.text and "synthetic-model-secret" not in html.text
    csrf = re.search(r'name="wo-token" content="([^"]+)"', html.text)[1]
    assert client.get("/api/overview").status_code == 200
    assert client.post("/api/import", json=jd()).status_code == 403
    assert client.post("/api/import", json=jd(), headers={"X-WO-Token": csrf}).status_code == 201
    client.cookies.clear()
    bearer = {"Authorization": "Bearer " + ACCESS}
    assert client.get("/api/jobs", headers=bearer).status_code == 200
    assert client.post("/api/import", json=jd(), headers=bearer).status_code == 201
    assert client.post("/api/import", json=jd(), headers={"X-WO-Token": csrf}).status_code == 401


def test_fixed_host_origin_and_fetch_site_apply_even_to_authenticated_requests(deployed):
    client, _ = deployed
    bearer = {"Authorization": "Bearer " + ACCESS}
    for headers in (
        {"Host": "evil.example"},
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Host": "evil.example", "X-Forwarded-Host": "observer.example"},
    ):
        assert client.get("/api/jobs", headers={**bearer, **headers}).status_code == 403
    assert client.get("/api/jobs", headers={**bearer, "Origin": ORIGIN}).status_code == 200
    assert (
        client.post(
            "/login", data={"token": ACCESS}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_login_failure_budget_and_malformed_credentials_fail_safely(deployed):
    client, _ = deployed
    for _ in range(10):
        failed = client.post("/login", data={"token": "错误口令"})
        assert failed.status_code == 200 and "错误口令" not in failed.text
    limited = client.post("/login", data={"token": ACCESS})
    assert limited.status_code == 429 and limited.json()["error_code"] == "LOGIN_RATE_LIMIT"
    assert limited.headers["cache-control"] == "no-store"


def test_forged_expired_and_oversized_cookies_are_unauthenticated(deployed):
    client, settings = deployed
    guard = DeploymentGuard(None, settings=settings)
    for value in ("forged", guard.session("1"), "9" * 5000 + ".bad", "12345678900.bad"):
        assert client.get("/api/jobs", headers={"Cookie": "wo_session=" + value}).status_code == 401
    too_large = client.post("/login", content=b"token=" + b"x" * 3000)
    assert too_large.status_code == 400
    assert client.post("/login", content=b"token=\xff").status_code == 200
