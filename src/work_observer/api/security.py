"""可部署单用户访问层：固定Origin、令牌登录、签名会话、有限失败尝试。"""

import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from work_observer.config import validate_url
from work_observer.connectors.mcp_probe import ProbeError

COOKIE = "wo_session"


def deployment_settings(settings):
    origin = settings.public_origin
    token = settings.access_token.get_secret_value()
    if not origin and not token:
        return None
    if (
        len(token) < 32
        or len(token) > 512
        or not origin
        or not token.isascii()
        or any(char.isspace() for char in token)
    ):
        raise ProbeError("DEPLOYMENT_ACCESS_CONFIG_REQUIRED")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProbeError("DEPLOYMENT_HTTPS_REQUIRED")
    origin = validate_url(origin)
    if urlsplit(origin).path not in {"", "/"}:
        raise ProbeError("DEPLOYMENT_ORIGIN_MUST_BE_ROOT")
    return origin.rstrip("/"), token


class DeploymentGuard:
    def __init__(self, app, *, settings):
        self.app = app
        self.config = deployment_settings(settings)
        self.attempts = {}

    def session(self, expiry):
        signature = hmac.new(self.config[1].encode(), expiry.encode(), hashlib.sha256).hexdigest()
        return expiry + "." + signature

    def authenticated(self, request):
        token = self.config[1]
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer ") and secrets.compare_digest(
            authorization[7:].encode(), token.encode()
        ):
            return True, True
        cookie = request.cookies.get(COOKIE, "")
        expiry, _, _ = cookie.partition(".")
        if (
            len(expiry) <= 12
            and expiry.isascii()
            and expiry.isdecimal()
            and time.time() < int(expiry) <= time.time() + 43260
        ):
            return secrets.compare_digest(cookie.encode(), self.session(expiry).encode()), False
        return False, False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.config:
            return await self.app(scope, receive, send)
        request = Request(scope, receive=receive)
        origin, _ = self.config
        # 反向代理必须保留Host；不信任任意转发头。
        if request.headers.get("host", "") != urlsplit(origin).netloc:
            return await JSONResponse(
                {"error_code": "INVALID_HOST", "message": "请使用已配置的工作空间地址。"}, 403
            )(scope, receive, send)
        supplied_origin = request.headers.get("origin")
        if (supplied_origin and supplied_origin != origin) or request.headers.get(
            "sec-fetch-site"
        ) == "cross-site":
            return await JSONResponse(
                {"error_code": "INVALID_ORIGIN", "message": "请从当前工作空间发起操作。"}, 403
            )(scope, receive, send)
        if request.url.path == "/login":
            response = await self.login(request)
            return await response(scope, receive, send)
        if request.url.path == "/assets/app.css":
            return await self.app(scope, receive, send)
        authenticated, bearer = self.authenticated(request)
        if not authenticated:
            response = (
                JSONResponse({"error_code": "AUTH_REQUIRED", "message": "请先登录工作空间。"}, 401)
                if request.url.path.startswith("/api/")
                else RedirectResponse("/login", 303)
            )
            return await response(scope, receive, send)
        scope["wo_bearer_authenticated"] = bearer
        await self.app(scope, receive, send)

    async def login(self, request):
        error = ""
        if request.method == "POST":
            client = request.client.host if request.client else "unknown"
            stamp = time.monotonic()
            self.attempts = {
                key: values for key, values in self.attempts.items() if values[-1] > stamp - 60
            }
            if client not in self.attempts and len(self.attempts) >= 1000:
                return JSONResponse(
                    {"error_code": "LOGIN_RATE_LIMIT", "message": "尝试过于频繁，请稍后再试。"},
                    429,
                    headers={"cache-control": "no-store"},
                )
            attempts = self.attempts.setdefault(client, [])
            attempts[:] = [value for value in attempts if value > stamp - 60]
            if len(attempts) >= 10:
                return JSONResponse(
                    {"error_code": "LOGIN_RATE_LIMIT", "message": "尝试过于频繁，请稍后再试。"},
                    429,
                    headers={"cache-control": "no-store"},
                )
            attempts.append(stamp)
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > 2048:
                    return JSONResponse(
                        {"error_code": "INVALID_LOGIN", "message": "登录内容不符合要求。"}, 400
                    )
            try:
                value = parse_qs(body.decode(), max_num_fields=3).get("token", [""])[0]
            except (ValueError, UnicodeError):
                value = ""
            if value and secrets.compare_digest(value.encode(), self.config[1].encode()):
                response = RedirectResponse("/", 303)
                response.set_cookie(
                    COOKIE,
                    self.session(str(int(time.time()) + 43200)),
                    max_age=43200,
                    httponly=True,
                    samesite="strict",
                    secure=self.config[0].startswith("https://"),
                )
                response.headers["cache-control"] = "no-store"
                return response
            error = "访问口令不正确，请核对服务配置。"
        elif request.method != "GET":
            return JSONResponse(
                {"error_code": "METHOD_NOT_ALLOWED", "message": "不支持此登录操作。"}, 405
            )
        html = (
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>登录 · Work Observer</title><link rel="stylesheet" href="/assets/app.css">'
            '<main class="panel research-form"><h1>Work Observer</h1>'
            "<p>使用部署时配置的访问口令进入你的工作空间。</p>"
            '<form method="post" action="/login"><label>访问口令'
            '<input type="password" name="token" required autocomplete="current-password"></label>'
            f'<p role="status">{error}</p><button class="primary">进入工作空间</button>'
            "</form></main></html>"
        )
        return HTMLResponse(
            html,
            headers={
                "cache-control": "no-store",
                "content-security-policy": "default-src 'self'; style-src 'self'; "
                "frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
            },
        )
