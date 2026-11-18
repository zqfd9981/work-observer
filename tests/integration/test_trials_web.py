"""有限本地检索试用HTTP机制；人工动作全为合成actor，不是真实用户人审。"""

import re
from uuid import uuid4

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.quality.service import freeze, lock_suite, paired_evaluation
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def prepare(tmp_path):
    database = tmp_path / "app.db"
    upgrade(database)
    repository = Repository(database)
    job = import_jd(
        repository,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成有限试用岗位",
            company="合成公司",
            data_kind="synthetic",
            description="构建智能体，负责资料解析、记忆存储、工具路由和评测数据。",
        ),
    )["job_id"]
    repository.close()
    aliases = {
        "Agent": ["智能体"],
        "文档处理": ["资料解析"],
        "Memory": ["记忆存储"],
        "Tool routing": ["工具路由"],
        "Evaluation": ["评测数据"],
    }
    bundles = []
    for independent in (True, False):
        identity = uuid4().hex
        directory = tmp_path / "quality-trials" / identity
        freeze(database, directory)
        cases = []
        for index, (term, values) in enumerate(aliases.items()):
            cases.append(
                {
                    "id": str(index),
                    "split": "development" if index == 0 else "holdout",
                    "question": "synthetic-holdout-question-not-for-agent-" + str(index)
                    if index
                    else "合成开发查询",
                    "terms": [term],
                    "relevant": [
                        {"job_id": job, "quote": values[0], "reason": "合成标签，测试actor扮演人类"}
                    ],
                    "critical": True,
                    "notes": "synthetic mechanism only, not real human labels",
                }
            )
        lock_suite(
            directory,
            cases,
            label_origin="human" if independent else "agent_assisted",
            reviewer="synthetic-human-fixture-actor",
            independent_labels=independent,
        )
        paired_evaluation(directory, aliases)
        paired_evaluation(directory, aliases, phase="holdout")
        bundles.append(identity)
    return database, job, bundles


def test_trials_http_human_gate_budget_feedback_default_baseline_and_restart(tmp_path):
    database, job, bundles = prepare(tmp_path)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    options = {"reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **options), base_url="http://127.0.0.1") as client:
        page = client.get("/").text
        auth = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', page)[1]}
        assert 'id="page-trials"' in page
        assert client.get("/assets/trials.js").status_code == 200
        public = client.get("/api/trials")
        assert "synthetic-holdout-question-not-for-agent" not in public.text
        assert len(public.json()["bundles"]) == 2
        shadow_body = {
            "bundle_id": bundles[0],
            "job_ids": [job],
            "allowed_terms": ["Agent"],
            "max_uses": 2,
            "expires_hours": 1,
        }
        shadow = client.post("/api/trials/shadows", headers=auth, json=shadow_body)
        assert shadow.status_code == 201
        trial = shadow.json()
        assert trial["data_mode"] == "synthetic" and trial["state"] == "awaiting_review"
        assert trial["shadow"]["queries"][0]["candidate_evidence"]
        assert "synthetic-holdout-question-not-for-agent" not in shadow.text
        path = "/api/trials/" + trial["id"]
        first = client.post(
            path + "/search",
            headers=auth,
            json={"terms": ["Agent"], "request_key": "before-review"},
        )
        assert first.json()["mode"] == "baseline"
        review = {
            "reviewer": "synthetic-human-fixture-actor",
            "decision": "approve",
            "reason": "合成fixture动作，非真实人审结果",
            "labels_independent_confirmed": True,
        }
        denied = client.post(
            path + "/review", headers=auth, json={**review, "reviewer_kind": "agent_assisted"}
        )
        assert denied.json()["error_code"] == "TRIAL_INDEPENDENT_HUMAN_APPROVAL_REQUIRED"
        approved = client.post(path + "/review", headers=auth, json=review)
        assert approved.json()["state"] == "active"
        for _ in range(2):
            result = client.post(
                path + "/search",
                headers=auth,
                json={"terms": ["Agent"], "request_key": "same-request"},
            )
            assert result.json()["mode"] == "limited_candidate" and result.json()["uses"] == 1
        default = client.post(
            "/api/retrieval", headers=auth, json={"terms": ["Agent"], "job_ids": [job]}
        )
        assert default.json()["retrieval"]["evidence"] == []
        feedback = client.post(
            path + "/feedback",
            headers=auth,
            json={
                "request_key": "same-request",
                "rating": "fail",
                "note": "合成质量反馈：有误召回",
            },
        )
        assert feedback.json()["state"] == "rolled_back"
        assert (
            client.post(
                path + "/search",
                headers=auth,
                json={"terms": ["Agent"], "request_key": "same-request"},
            ).json()["mode"]
            == "baseline"
        )
        blocked = client.post(
            "/api/trials/shadows", headers=auth, json={**shadow_body, "bundle_id": bundles[1]}
        ).json()
        assert blocked["state"] == "insufficient"
        attempted = client.post(
            "/api/trials/" + blocked["id"] + "/review", headers=auth, json=review
        )
        assert attempted.json()["error_code"] == "TRIAL_REAL_LABELS_OR_EVALUATION_INSUFFICIENT"
        assert (
            client.post(
                "/api/trials/shadows", headers=auth, json={**shadow_body, "path": "C:/arbitrary"}
            ).status_code
            == 422
        )
        assert client.post("/api/trials/shadows", json=shadow_body).status_code == 403
        assert "/api/trials/{id}/feedback" in client.get("/api/openapi.json").json()["paths"]
    with TestClient(create_app(settings, **options), base_url="http://127.0.0.1") as client:
        detail = client.get(path).json()
        assert detail["trial"]["state"] == "rolled_back"
        assert detail["trial"]["uses"] == 1
        assert any(event["action"] == "automatic_rollback" for event in detail["events"])
        assert len(client.get("/api/trials").json()["trials"]) == 2
