"""URL and response-size guards on the curated scraper.

The source list is meant to be operator-curated, but "the list is curated" is a
convention and these are the controls. Every case here fails if the guard is
removed.
"""

import httpx
import pytest

from hailmary.clients.feeds.scraper import (
    MAX_RESPONSE_BYTES,
    UnsafeSourceURLError,
    assert_safe_url,
    fetch_docs,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/recap",
        "https://example.com/recap",
        "https://sub.example.co.uk/a/b?c=d",
        "https://93.184.216.34/recap",  # a public IP literal is fine
    ],
)
def test_public_http_urls_are_allowed(url):
    assert_safe_url(url)  # must not raise


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/x",
        "data:text/html,hello",
    ],
)
def test_non_http_schemes_are_refused(url):
    with pytest.raises(UnsafeSourceURLError):
        assert_safe_url(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata, the classic SSRF target
        "http://127.0.0.1:8000/admin",
        "http://localhost/admin",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "http://172.16.0.1/internal",
        "http://[::1]/admin",
        "http://0.0.0.0/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_internal_targets_are_refused(url):
    with pytest.raises(UnsafeSourceURLError):
        assert_safe_url(url)


@pytest.mark.unit
def test_url_without_a_host_is_refused():
    with pytest.raises(UnsafeSourceURLError):
        assert_safe_url("http:///nohost")


class _FakeStream:
    """Minimal stand-in for httpx's streaming context manager."""

    def __init__(self, *, url, body=b"<p>hello world</p>", headers=None, raise_status=None):
        self.url = url
        self._body = body
        self.headers = headers or {}
        self.encoding = "utf-8"
        self._raise_status = raise_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self._raise_status is not None:
            raise self._raise_status

    async def aiter_bytes(self):
        for i in range(0, len(self._body), 1024):
            yield self._body[i : i + 1024]


class FakeClient:
    def __init__(self, response):
        self._response = response
        self.requested: list[str] = []

    def stream(self, method, url, **kwargs):
        self.requested.append(url)
        return self._response


SOURCE = {"url": "https://example.com/recap", "sport": "nfl", "doc_type": "game_recap"}


@pytest.mark.unit
async def test_fetch_docs_returns_a_doc_for_a_safe_source():
    client = FakeClient(_FakeStream(url="https://example.com/recap"))
    docs = await fetch_docs([SOURCE], client)

    assert len(docs) == 1
    assert docs[0].source == "https://example.com/recap"
    assert "hello world" in docs[0].text


@pytest.mark.unit
async def test_fetch_docs_never_requests_an_unsafe_source():
    """The guard must run before the request, not after — otherwise the SSRF has
    already happened by the time we decide to skip the document."""
    client = FakeClient(_FakeStream(url="http://169.254.169.254/"))
    unsafe = {**SOURCE, "url": "http://169.254.169.254/latest/meta-data/"}

    docs = await fetch_docs([unsafe], client)

    assert docs == []
    assert client.requested == [], "no HTTP request may be issued for a refused URL"


@pytest.mark.unit
async def test_fetch_docs_drops_a_page_that_redirected_to_an_internal_host():
    """Vetting the configured URL is not enough: redirects are followed, so the
    URL actually fetched can differ from the one that was checked."""
    client = FakeClient(_FakeStream(url="http://127.0.0.1:8000/admin"))

    docs = await fetch_docs([SOURCE], client)

    assert docs == []


@pytest.mark.unit
async def test_fetch_docs_abandons_a_body_over_the_byte_cap():
    oversized = b"x" * (MAX_RESPONSE_BYTES + 1)
    client = FakeClient(_FakeStream(url="https://example.com/recap", body=oversized))

    docs = await fetch_docs([SOURCE], client)

    assert docs == []


@pytest.mark.unit
async def test_fetch_docs_rejects_an_oversized_declared_content_length():
    client = FakeClient(
        _FakeStream(
            url="https://example.com/recap",
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
        )
    )

    docs = await fetch_docs([SOURCE], client)

    assert docs == []


@pytest.mark.unit
async def test_fetch_docs_skips_a_failing_page_without_sinking_the_pass():
    good = {**SOURCE, "url": "https://example.com/good"}

    class TwoPageClient:
        def __init__(self):
            self.requested: list[str] = []

        def stream(self, method, url, **kwargs):
            self.requested.append(url)
            if url.endswith("/bad"):
                return _FakeStream(
                    url=url,
                    raise_status=httpx.HTTPStatusError(
                        "500", request=httpx.Request("GET", url), response=httpx.Response(500)
                    ),
                )
            return _FakeStream(url=url)

    client = TwoPageClient()
    docs = await fetch_docs([{**SOURCE, "url": "https://example.com/bad"}, good], client)

    assert len(docs) == 1
    assert docs[0].source == "https://example.com/good"
