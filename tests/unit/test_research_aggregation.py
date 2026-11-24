from work_observer.reports.aggregation import aggregate_research


def sample():
    return {
        "scope": {"jobs": [{"id": key, "has_detail": key != "missing"}
                           for key in ("a", "b", "missing", "unread")]},
        "evidence": [{"id": "E1", "job_id": "a", "document_id": "doc-a"},
                     {"id": "E2", "job_id": "a", "document_id": "doc-a"},
                     {"id": "E3", "job_id": "b", "document_id": "doc-b"}],
        "claims": [],
    }


def claim(kind="none", evidence_ids=None, basis="synthesis"):
    return {"category": "ability", "basis": basis, "aggregation": kind,
            "requirement": "unspecified", "text": "合成判断，不代表真实市场",
            "evidence_ids": evidence_ids or ["E1", "E2", "E3"]}


def test_aggregation_counts_jobs_not_passages_and_preserves_unknown_scope():
    result = sample()
    result["claims"] = [claim("common"), claim("difference"), claim("exception", ["E2"]),
                        claim("calibration")]
    layer = aggregate_research(result)
    assert layer["cited_sources"] == layer["cited_jobs"] == 2
    assert layer["candidate_jobs"] == 4
    assert layer["available_details"] == 3
    assert layer["read_jobs"] == 2
    assert layer["missing_detail_ids"] == ["missing"]
    assert layer["unread_job_ids"] == ["unread"]
    assert [row["kind"] for row in layer["groups"]] == [
        "common", "difference", "exception", "calibration",
    ]
    assert layer["groups"][2]["job_ids"] == ["a"]
    assert "不是需求频次" in layer["notice"]


def test_single_source_cannot_be_presented_as_cross_source_common_ground():
    result = sample()
    result["claims"] = [claim("common", ["E1", "E2"])]
    assert aggregate_research(result) is None
    result["claims"].append(claim("difference"))
    assert aggregate_research(result)["groups"][0]["kind"] == "single_source"


def test_no_aggregation_is_invented_from_unrelated_individual_facts_or_missing_quotes():
    result = sample()
    result["claims"] = [claim(evidence_ids=["E1"], basis="direct"),
                        claim(evidence_ids=["E3"], basis="direct")]
    assert aggregate_research(result) is None
    result["claims"] = [claim("common", ["nonexistent"])]
    assert aggregate_research(result) is None


def test_prior_synthesis_is_indexed_without_inventing_a_common_or_exception_label():
    result = sample()
    result["claims"] = [claim()]
    assert aggregate_research(result)["groups"][0]["kind"] == "pattern"


def test_public_document_versions_are_one_source_and_are_not_counted_as_jobs():
    result = {"scope": {"jobs": []}, "evidence": [
        {"id": "E1", "public_document_id": "a", "document_id": "v1"},
        {"id": "E2", "public_document_id": "a", "document_id": "v2"},
        {"id": "E3", "public_document_id": "b", "document_id": "v3"},
    ], "claims": [claim("common")]}
    layer = aggregate_research(result)
    assert layer["cited_sources"] == 2
    assert layer["cited_jobs"] == layer["candidate_jobs"] == 0
