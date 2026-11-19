"""公开正文归档与固定公网IP连接的隔离测试，不执行网络请求。"""

import asyncio
import hashlib
import ipaddress
import socket
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from work_observer.connectors import public_documents as module
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def service(tmp_path):
    path = tmp_path / "public.db"
    upgrade(path)
    repo = Repository(path)
    yield PublicDocumentService(repo, tmp_path / "archive")
    repo.close()


def test_html_archive_retains_raw_bytes_and_verifiable_exact_plain_text(service, monkeypatch):
    raw = (
        "<html><head><title>模拟官网</title><script>secret script</script></head>"
        "<body><nav>菜单</nav><main><h1>产品介绍</h1><p>提供智能体开发工具。</p>"
        "<style>hide</style><template>隐藏的编译代码与页面索引"
        "<script>nested payload</script>still hidden</template></main></body></html>"
    ).encode()

    async def fetch(url):
        return 200, {"content-type": "text/html; charset=utf-8"}, raw

    monkeypatch.setattr(module, "pinned_request", fetch)
    result = asyncio.run(service.read("https://example.com/docs"))
    identity = result["document"]["id"]
    archived = service.document(identity)
    assert archived["title"] == "模拟官网"
    assert archived["text"] == "产品介绍\n提供智能体开发工具。"
    assert archived["source_published_at"] is None
    assert archived["integrity"] == "verified"
    assert archived["sha256"] == hashlib.sha256(raw).hexdigest()
    assert "path" not in archived
    evidence = result["evidence"][0]
    assert evidence["evidence_kind"] == "public_document"
    assert evidence["provider_synthesized"] is False
    assert evidence["public_document_id"] == identity
    assert archived["text"][evidence["start"] : evidence["end"]] == evidence["quote"]
    with Session(service.repository.engine) as session:
        source = Path(session.get(PublicDocument, identity).path)
    assert source.read_bytes() == raw
    source.write_bytes(b"modified")
    assert service.document(identity)["integrity"] == "missing_or_changed"


def test_public_text_has_bounded_evidence_but_full_archive(service, monkeypatch):
    async def fetch(url):
        return 200, {"content-type": "text/plain"}, ("模拟文本" * 3000).encode()

    monkeypatch.setattr(module, "pinned_request", fetch)
    result = asyncio.run(service.read("https://example.com/docs"))
    assert result["truncated"]
    assert len(result["evidence"]) == 8
    assert all(len(item["quote"]) <= 700 for item in result["evidence"])
    assert len(service.document(result["document"]["id"])["text"]) == 12000


@pytest.mark.parametrize(
    "target", ["http://example.com/", "https://127.0.0.1/", "https://example.com/?token=x"]
)
def test_redirect_revalidates_next_destination_before_connection(service, monkeypatch, target):
    calls = []

    async def fetch(url):
        calls.append(url)
        return 302, {"location": target}, b""

    monkeypatch.setattr(module, "pinned_request", fetch)
    with pytest.raises(ProbeError, match="PUBLIC_DOCUMENT_URL_DENIED"):
        asyncio.run(service.read("https://example.com/docs"))
    assert calls == ["https://example.com/docs"]


def test_redirect_limit_and_relative_redirect(service, monkeypatch):
    calls = []

    async def fetch(url):
        calls.append(url)
        return 302, {"location": "/next"}, b""

    monkeypatch.setattr(module, "pinned_request", fetch)
    with pytest.raises(ProbeError, match="PUBLIC_DOCUMENT_REDIRECT_LIMIT"):
        asyncio.run(service.read("https://example.com/docs"))
    assert len(calls) == 3
    assert calls[1] == "https://example.com/next"


def reader_for(data):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class Writer:
    def __init__(self):
        self.sent = b""
        self.closed = False

    def write(self, data):
        self.sent += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def test_dns_resolution_is_global_and_connection_pins_ip_with_original_tls_hostname(monkeypatch):
    async def scenario():
        connections, resolutions = [], []
        writer = Writer()

        async def resolve(hostname, port, **kwargs):
            resolutions.append((hostname, port))
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

        async def connect(host, port, **kwargs):
            connections.append((host, port, kwargs))
            return reader_for(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 4\r\n\r\ntext"
            ), writer

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        monkeypatch.setattr(asyncio, "open_connection", connect)
        status, _, body = await module.pinned_request("https://example.com/docs")
        assert status == 200 and body == b"text"
        assert resolutions == [("example.com", 443)]
        assert connections[0][0] == "93.184.216.34"
        assert connections[0][2]["server_hostname"] == "example.com"
        assert connections[0][2]["ssl"].check_hostname
        assert b"Host: example.com\r\n" in writer.sent
        assert b"Accept-Encoding: identity\r\n" in writer.sent
        assert b"Authorization" not in writer.sent and b"Cookie" not in writer.sent
        assert writer.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "blocked", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "100.64.0.1"]
)
def test_any_private_dns_result_blocks_all_connections(monkeypatch, blocked):
    async def scenario():
        async def resolve(hostname, port, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (
                    socket.AF_INET6
                    if ipaddress.ip_address(blocked).version == 6
                    else socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (blocked, 443),
                ),
            ]

        async def forbidden(*args, **kwargs):
            pytest.fail("private or mixed DNS must not open a socket")

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        monkeypatch.setattr(asyncio, "open_connection", forbidden)
        with pytest.raises(ProbeError, match="PUBLIC_DOCUMENT_DNS_DENIED"):
            await module.pinned_request("https://example.com/docs")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "headers,body,code",
    [
        ({"content-length": "1000001"}, b"", "TOO_LARGE"),
        ({"transfer-encoding": "chunked"}, b"f4241\r\n", "TOO_LARGE"),
        ({"content-encoding": "gzip"}, b"", "ENCODING_UNSUPPORTED"),
        ({"content-length": "4", "transfer-encoding": "chunked"}, b"", "INVALID_HTTP"),
    ],
)
def test_http_body_limits_and_compression_are_enforced(headers, body, code):
    async def scenario():
        with pytest.raises(ProbeError, match=code):
            await module._read_body(reader_for(body), headers)

    asyncio.run(scenario())


def test_chunked_plaintext_is_decoded_without_unbounded_reads():
    async def scenario():
        result = await module._read_body(
            reader_for(b"4\r\ntext\r\n3\r\nabc\r\n0\r\n\r\n"), {"transfer-encoding": "chunked"}
        )
        assert result == b"textabc"

    asyncio.run(scenario())


def test_html_meta_refresh_follows_public_target_and_archives_final_body(service, monkeypatch):
    calls = []

    async def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            return (
                200,
                {"content-type": "text/html"},
                (
                    b'<meta http-equiv="refresh" content="0;url=https://docs.example.com/overview">'
                    b'<link rel="canonical" href="https://other.example.com/not-followed">Redirecting...'
                ),
            )
        return (
            200,
            {"content-type": "text/html"},
            "<title>模拟文档</title><p>实际技术说明正文。</p>".encode(),
        )

    monkeypatch.setattr(module, "pinned_request", fetch)
    result = asyncio.run(service.read("https://example.com/old"))
    assert calls == ["https://example.com/old", "https://docs.example.com/overview"]
    assert result["document"]["url"] == "https://example.com/old"
    assert result["document"]["final_url"] == "https://docs.example.com/overview"
    assert result["document"]["extractor_version"] == "public-html-v3"
    assert result["evidence"][0]["quote"] == "实际技术说明正文。"


def test_canonical_alone_does_not_trigger_fetch(service, monkeypatch):
    calls = []

    async def fetch(url):
        calls.append(url)
        return (
            200,
            {"content-type": "text/html"},
            (
                b'<link rel="canonical" href="https://other.example.com/">'
                b"<p>Actual document body.</p>"
            ),
        )

    monkeypatch.setattr(module, "pinned_request", fetch)
    result = asyncio.run(service.read("https://example.com/doc"))
    assert len(calls) == 1
    assert result["document"]["final_url"] == "https://example.com/doc"


@pytest.mark.parametrize(
    "body,code",
    [
        (b"<p>Redirecting to new documentation...</p>", "REDIRECT_ONLY"),
        (
            b'<script>window.location.href="https://docs.example.com"</script>',
            "UNSUPPORTED_CLIENT_REDIRECT",
        ),
        (b'<meta http-equiv="refresh" content="0;url=https://127.0.0.1/">', "URL_DENIED"),
        (b'<meta http-equiv="refresh" content="0">', "UNSUPPORTED_CLIENT_REDIRECT"),
    ],
)
def test_redirect_stubs_cannot_be_reported_as_document_body(service, monkeypatch, body, code):
    calls = []

    async def fetch(url):
        calls.append(url)
        return 200, {"content-type": "text/html"}, body

    monkeypatch.setattr(module, "pinned_request", fetch)
    with pytest.raises(ProbeError, match=code):
        asyncio.run(service.read("https://example.com/old"))
    assert len(calls) == 1


def test_meta_and_http_redirects_share_same_two_hop_budget(service, monkeypatch):
    calls = []

    async def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            return 301, {"location": "/new"}, b""
        return (
            200,
            {"content-type": "text/html"},
            b'<meta http-equiv="refresh" content="0;url=/more">',
        )

    monkeypatch.setattr(module, "pinned_request", fetch)
    with pytest.raises(ProbeError, match="REDIRECT_LIMIT"):
        asyncio.run(service.read("https://example.com/old"))
    assert len(calls) == 3
