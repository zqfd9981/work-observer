"""来源转换的隔离测试；这些示例不是平台连通证据。"""

import pytest

from work_observer.connectors.boss_detail import normalize_boss_detail
from work_observer.connectors.mcp_probe import ProbeError


def response(**overrides):
    return {
        "code": 0,
        "zpData": {
            "jobInfo": {
                "encryptId": "simulated-job",
                "jobName": "模拟岗位",
                "postDescription": "完整模拟正文\n职责与要求",
                "jobStatusDesc": "招聘中",
                "invalidStatus": False,
                "jobType": 0,
                **overrides,
            },
            "brandComInfo": {"brandName": "模拟公司", "encryptBrandId": "simulated-company"},
        },
    }


def test_response_preserves_full_body_and_does_not_guess_type_or_publish_time():
    raw = response()
    record = normalize_boss_detail(
        raw, "simulated-job", {"security_id": "simulated-access", "lid": "simulated-lid"}
    )
    assert record["description"] == raw["zpData"]["jobInfo"]["postDescription"]
    assert record["source_company_id"] == "simulated-company"
    assert record["source_status_raw"]["jobStatusDesc"] == "招聘中"
    assert record["lid"] == "simulated-lid"
    assert "employment_type" not in record and "source_published_at" not in record


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"encryptId": "another-job"}, "DETAIL_ID_MISMATCH"),
        ({"postDescription": "  "}, "MISSING_DETAIL_DESCRIPTION"),
    ],
)
def test_wrong_identity_or_missing_body_is_never_accepted(overrides, code):
    with pytest.raises(ProbeError, match=code):
        normalize_boss_detail(response(**overrides), "simulated-job", {})
