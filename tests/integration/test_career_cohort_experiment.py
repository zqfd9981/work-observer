"""The metric experiment computes explicit counts and saves only on request."""

import re
from copy import deepcopy

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.cohort_experiment import CohortCasesInput, run_cohort_experiment
from work_observer.storage.database import upgrade

GROUPS = [
    {"name": "高意向", "before_total": 100, "before_converted": 90,
     "after_total": 400, "after_converted": 320},
    {"name": "低意向", "before_total": 400, "before_converted": 40,
     "after_total": 100, "after_converted": 5},
]
INPUT = {"groups": GROUPS, "metric": "完成注册数 / 访问人数",
         "conditions": "虚构样例，假定口径与分群定义一致；占比发生变化。", "data_kind": "synthetic"}


def test_group_and_pooled_rates_reverse_without_changing_the_inputs():
    before = deepcopy(INPUT)
    result = run_cohort_experiment(**INPUT)
    assert result["overall"]["before_rate"] == pytest.approx(.26)
    assert result["overall"]["after_rate"] == pytest.approx(.65)
    assert result["overall"]["after_with_before_mix"] == pytest.approx(.20)
    assert result["overall"]["change_with_before_mix"] == pytest.approx(-.06)
    assert all(row["change"] < 0 for row in result["groups"])
    assert result["overall"]["composition_reversal"] is True
    assert result["groups"][0]["before_share"] == pytest.approx(.2)
    assert result["groups"][0]["after_share"] == pytest.approx(.8)
    assert INPUT == before
    assert "构造的虚构数据" in result["artifact_text"] and "320" in result["artifact_text"]


def test_missing_denominators_remain_unknown_instead_of_becoming_zero():
    groups = [{"name": "原有人群", "before_total": 100, "before_converted": 20,
               "after_total": 0, "after_converted": 0},
              {"name": "新人群", "before_total": 0, "before_converted": 0,
               "after_total": 10, "after_converted": 5}]
    result = run_cohort_experiment(**{**INPUT, "groups": groups})
    assert result["groups"][0]["after_rate"] is None
    assert result["groups"][1]["before_rate"] is None
    assert result["overall"]["after_with_before_mix"] is None
    assert result["overall"]["composition_reversal"] is None
    empty = [{**row, "before_total": 0, "before_converted": 0,
              "after_total": 0, "after_converted": 0} for row in groups]
    assert run_cohort_experiment(**{**INPUT, "groups": empty})["overall"]["before_rate"] is None
    for bad in [
        [{**GROUPS[0], "before_converted": 101}],
        [{**GROUPS[0], "after_total": -1}],
        [{**GROUPS[0], "before_total": True}],
        [GROUPS[0], GROUPS[0]],
    ]:
        with pytest.raises(ValidationError):
            CohortCasesInput.model_validate({**INPUT, "groups": bad})


class NoModel:
    async def turn(self, history):
        raise AssertionError("The local calculator must not call a provider")


def test_preview_is_read_only_and_save_retains_exact_counts_conditions_and_inquiry(tmp_path):
    database = tmp_path / "cohort.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=NoModel(), reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        response = client.post("/api/career", headers=auth, json={
            "title": "合成指标学习实验", "goal": "检验总体数字与分群条件",
            "first_question": "总体上涨，是否说明各人群都改善？",
            "material_title": "合成产品工作说明", "material_text": "应核对指标口径与样本构成。",
        })
        assert response.status_code == 201, response.text
        goal = response.json()
        identity, qid = goal["id"], goal["focus_question_id"]
        base = "/api/career/" + identity
        before = client.get(base).json()
        payload = {**INPUT, "question_id": qid, "hypothesis": "总体上涨是否就代表各人群改善？"}
        result = client.post(base + "/experiments/cohorts", headers=auth, json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["experiment"]["overall"]["composition_reversal"]
        assert client.get(base).json() == before
        for bad in [{"question_id": "0" * 32},
                    {"groups": [{**GROUPS[0], "after_converted": 401}]}]:
            response = client.post(base + "/experiments/cohorts", headers=auth,
                                   json={**payload, **bad, "save": True})
            assert response.status_code == 422, response.text
            assert client.get(base).json() == before
        response = client.post(base + "/experiments/cohorts", headers=auth,
                               json={**payload, "save": True})
        assert response.status_code == 201, response.text
        task_id = response.json()["task_id"]
        after = client.get(base).json()
        task = next(row for row in after["tasks"] if row["id"] == task_id)
        assert task["question_id"] == qid and task["state"] == "done"
        assert task["hypothesis"] == payload["hypothesis"]
        assert task["comparison_conditions"] == INPUT["conditions"]
        artifact = client.get("/api/public-documents/" + task["artifact_document_id"]).json()
        assert '"before_total": 100' in artifact["text"] and '"after_converted": 320' in (
            artifact["text"]
        )
        assert "构造的虚构数据" in artifact["text"] and "因果验证" in artifact["text"]
        assert after["questions"] == before["questions"] and after["usage"] == before["usage"]
        assert not after["results"] and not after["insights"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        restored = client.get(base).json()
        assert restored["tasks"][0] == task
