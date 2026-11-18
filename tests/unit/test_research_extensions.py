"""隔离模拟搜索与详情历史机制；不声称真实公开服务或招聘连通。"""

import asyncio
import json

import httpx
import pytest

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_search import PublicSearch, public_url
from work_observer.research.history import HistoryService
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def mock_search(monkeypatch, body, status=200):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    return requests


def search_body():
    return {
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"sources": [{"url": "https://example.com/docs"}]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "模拟搜索生成摘要，含 test-secret；不是网页原文。",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/docs",
                                "title": "模拟官方文档",
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20, "private": "test-secret"},
    }


def search_settings(**kwargs):
    return Settings(
        model_base_url="https://example.com/v1",
        model_name="simulated",
        model_api_key="test-secret",
        **kwargs,
    )


def test_openai_search_requires_actual_call_and_citation_and_labels_derived_text(monkeypatch):
    requests = mock_search(monkeypatch, search_body())
    result = asyncio.run(PublicSearch(search_settings()).search("模拟官网产品"))
    assert len(requests) == result["search_calls"] == 1
    payload = json.loads(requests[0].content)
    assert payload["max_tool_calls"] == 1
    assert payload["store"] is False
    assert "test-secret" not in json.dumps(result)
    evidence = result["evidence"][0]
    assert evidence["provider_synthesized"]
    assert evidence["evidence_kind"] == "search_answer"
    assert evidence["job_id"] is evidence["snapshot_id"] is evidence["source_published_at"] is None
    assert evidence["quote"].startswith("模拟搜索")
    assert evidence["url"] == "https://example.com/docs"
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert result["cost"] is None


@pytest.mark.parametrize("case", ["missing_call", "two_calls", "missing_cite", "unknown_cite"])
def test_openai_search_rejects_unverified_or_unbounded_response(monkeypatch, case):
    body = search_body()
    if case == "missing_call":
        body["output"].pop(0)
    elif case == "two_calls":
        body["output"].append(body["output"][0])
    elif case == "missing_cite":
        body["output"][1]["content"][0]["annotations"] = []
    else:
        body["output"][1]["content"][0]["annotations"][0]["url"] = "https://else.example/docs"
    requests = mock_search(monkeypatch, body)
    with pytest.raises(ProbeError):
        asyncio.run(PublicSearch(search_settings()).search("模拟官网产品"))
    assert len(requests) == 1


def test_tavily_excerpt_and_unsafe_links_do_not_escape(monkeypatch):
    body = {
        "results": [
            {"url": "https://example.com/?token=private", "title": "拒绝", "content": "正文"},
            {"url": "http://example.com/", "title": "拒绝", "content": "正文"},
            {
                "url": "https://example.com/doc?utm_source=test#part",
                "title": "模拟",
                "content": "节选",
            },
        ]
    }
    requests = mock_search(monkeypatch, body)
    settings = search_settings(search_provider="tavily", tavily_api_key="other-secret")
    result = asyncio.run(PublicSearch(settings).search("模拟"))
    assert len(requests) == 1
    assert len(result["evidence"]) == 1
    evidence = result["evidence"][0]
    assert evidence["evidence_kind"] == "search_excerpt"
    assert evidence["provider_synthesized"] is False
    assert evidence["url"] == "https://example.com/doc"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com/doc",
        "https://example.com/?security_id=x",
        "https://127.0.0.1/doc",
        "https://[::1]/doc",
        "https://metadata.internal/doc",
        "https://example.com:3000/doc",
    ],
)
def test_public_url_rejects_credentials_internal_hosts_and_access_parameters(url):
    assert public_url(url) is None


def test_public_search_missing_config_and_invalid_queries_never_call_network(monkeypatch):
    requests = mock_search(monkeypatch, {})
    for settings, query in ((Settings(), "模拟"), (search_settings(), "x" * 301)):
        with pytest.raises(ProbeError):
            asyncio.run(PublicSearch(settings).search(query))
    assert requests == []


def test_public_search_error_does_not_reveal_raw_body(monkeypatch):
    requests = mock_search(monkeypatch, {"error": "test-secret private"}, status=429)
    with pytest.raises(ProbeError, match="PUBLIC_SEARCH_RATE_LIMIT_OR_QUOTA") as exc:
        asyncio.run(PublicSearch(search_settings()).search("模拟"))
    assert "test-secret" not in str(exc.value)
    assert len(requests) == 1


@pytest.fixture
def history_store(tmp_path):
    path = tmp_path / "history.db"
    upgrade(path)
    repository = Repository(path)
    archive = RawArchive(tmp_path / "raw")

    def add(description):
        return import_jd(
            repository,
            archive,
            ManualJD(
                title="模拟岗位", company="模拟公司", external_id="history", description=description
            ),
        )["job_id"]

    yield repository, add
    repository.close()


def test_history_does_not_infer_change_without_two_detail_versions(history_store):
    repository, add = history_store
    job_id = add("模拟职责：编写 Python")
    add("模拟职责：编写 Python")
    service = HistoryService(repository)
    assert service.list_versions(job_id)["distinct_detail_versions"] == 1
    result = service.compare(job_id)
    assert result["status"] == "insufficient_history"
    assert len(result["observations"]) == 2
    assert result["changes"] == result["evidence"] == []


def test_history_preserves_a_b_a_and_compares_latest_observed_transition(history_store):
    repository, add = history_store
    job_id = add("模拟职责：编写 Python")
    add("模拟职责：编写 Python，新增维护评估集")
    add("模拟职责：编写 Python")
    service = HistoryService(repository)
    history = service.list_versions(job_id)
    assert history["distinct_detail_versions"] == 2
    observations = history["observations"]
    assert observations[0]["snapshot_id"] == observations[2]["snapshot_id"]
    result = service.compare(job_id)
    assert result["status"] == "compared"
    assert result["before"]["snapshot_id"] == observations[1]["snapshot_id"]
    assert result["after"]["snapshot_id"] == observations[2]["snapshot_id"]
    assert result["changes"][0]["field"] == "description"
    assert "维护评估集" in result["description_diff"]
    assert {item["mode"] for item in result["evidence"]} == {"manual"}
    assert all(item["source_published_at"] is None for item in result["evidence"])
    for evidence in result["evidence"]:
        assert evidence["id"].startswith(evidence["snapshot_id"] + ":")
        assert evidence["end"] - evidence["start"] == len(evidence["quote"])


def test_history_rejects_cross_job_snapshot_and_reverse_order(history_store):
    repository, add = history_store
    job_id = add("模拟旧正文")
    add("模拟新正文")
    service = HistoryService(repository)
    versions = service.list_versions(job_id)["observations"]
    with pytest.raises(ProbeError, match="HISTORY_SNAPSHOT_NOT_FOUND"):
        service.compare(job_id, before_snapshot_id="outside")
    with pytest.raises(ProbeError, match="HISTORY_VERSION_ORDER_INVALID"):
        service.compare(job_id, versions[1]["snapshot_id"], versions[0]["snapshot_id"])


def test_history_restored_research_excludes_later_observations(history_store):
    repository, add = history_store
    job_id = add("模拟旧正文")
    service = HistoryService(repository)
    cutoff = service.list_versions(job_id)["observations"][-1]["processed_at"]
    add("模拟后续正文")
    result = service.compare(job_id, observed_before=cutoff)
    assert result["status"] == "insufficient_history"
    assert len(result["observations"]) == 1
