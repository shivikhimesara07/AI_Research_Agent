import xml.etree.ElementTree as ET

import httpx
import pytest

from app.models import PaperMeta
from app.services.s2_client import S2AuthError, S2BadRequest, S2TransientError
from app.services.search_service import (
    ArxivClient,
    SearchBadRequest,
    SearchService,
    SearchUnavailable,
    parse_arxiv_feed,
    s2_to_meta,
)

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2106.09685v2</id>
    <published>2021-06-17T17:37:18Z</published>
    <title>LoRA: Low-Rank Adaptation of
      Large Language Models</title>
    <summary>  An important paradigm
      of NLP.  </summary>
    <author><name>Edward J. Hu</name></author>
    <author><name> Yelong Shen </name></author>
    <link href="http://arxiv.org/abs/2106.09685v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2106.09685v2" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>bad-date</published>
    <title>Attention Is All You Need</title>
  </entry>
</feed>"""


# ---------- s2_to_meta ----------


def test_s2_to_meta_maps_fields_and_open_access_pdf():
    meta = s2_to_meta({
        "paperId": "abc", "title": " Title ", "year": 2020, "abstract": "Abs", "url": "https://s2/abc",
        "authors": [{"name": "A One"}, {"name": ""}, {"authorId": "1"}],
        "openAccessPdf": {"url": "https://oa/paper.pdf"},
        "externalIds": {"ArXiv": "2001.00001"},
    })
    assert meta == PaperMeta(source="semantic_scholar", external_id="abc", title="Title", authors=["A One"],
                             year=2020, abstract="Abs", url="https://s2/abc", pdf_url="https://oa/paper.pdf")


def test_s2_to_meta_builds_arxiv_pdf_url_when_no_open_access():
    meta = s2_to_meta({"paperId": "x", "title": "T", "openAccessPdf": None, "externalIds": {"ArXiv": "2106.09685"}})
    assert meta.pdf_url == "https://arxiv.org/pdf/2106.09685"


def test_s2_to_meta_handles_missing_fields():
    meta = s2_to_meta({"paperId": "x", "title": None, "authors": None, "openAccessPdf": {"url": ""}})
    assert meta.title == "Untitled" and meta.authors == [] and meta.pdf_url is None


# ---------- arXiv ----------


def test_parse_arxiv_feed():
    lora, attention = parse_arxiv_feed(ARXIV_FEED)
    assert lora.external_id == "arXiv:2106.09685"  # version suffix dropped
    assert lora.title == "LoRA: Low-Rank Adaptation of Large Language Models"  # whitespace collapsed
    assert lora.authors == ["Edward J. Hu", "Yelong Shen"]
    assert lora.year == 2021 and lora.abstract == "An important paradigm of NLP."
    assert lora.pdf_url == "http://arxiv.org/pdf/2106.09685v2"
    assert lora.source == "arxiv"
    # Sparse entry: no pdf link -> built from the id; unparseable date -> no year.
    assert attention.year is None and attention.abstract is None
    assert attention.pdf_url == "https://arxiv.org/pdf/1706.03762"


def test_parse_arxiv_feed_empty():
    assert parse_arxiv_feed('<feed xmlns="http://www.w3.org/2005/Atom"></feed>') == []


async def test_arxiv_client_ands_terms_and_sorts_by_relevance():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text=ARXIV_FEED)

    client = ArxivClient("https://arxiv.test/api/query", transport=httpx.MockTransport(handler))
    results = await client.search("low-rank (adaptation)!", limit=7)
    params = seen[0].url.params
    assert params["search_query"] == "all:low-rank AND all:adaptation"  # punctuation stripped
    assert params["sortBy"] == "relevance" and params["max_results"] == "7"
    assert len(results) == 2


async def test_arxiv_client_raises_on_http_error():
    client = ArxivClient("https://arxiv.test", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        await client.search("x")


# ---------- SearchService fallback rules ----------


class FakeS2:
    def __init__(self, result=None, error=None):
        self.result, self.error = result or [], error

    async def search(self, query, limit):
        if self.error:
            raise self.error
        return self.result


class FakeArxiv:
    def __init__(self, error=None):
        self.error, self.calls = error, 0

    async def search(self, query, limit):
        self.calls += 1
        if self.error:
            raise self.error
        return [PaperMeta(source="arxiv", external_id="arXiv:1", title="From arXiv")]


async def test_s2_results_are_returned_without_fallback():
    arxiv = FakeArxiv()
    resp = await SearchService(FakeS2([{"paperId": "p", "title": "From S2"}]), arxiv).search("q")
    assert resp.source == "semantic_scholar" and resp.fallback_reason is None
    assert [r.title for r in resp.results] == ["From S2"]
    assert arxiv.calls == 0


async def test_empty_s2_results_do_not_fall_back():
    arxiv = FakeArxiv()
    resp = await SearchService(FakeS2([]), arxiv).search("nonsense query")
    assert resp.source == "semantic_scholar" and resp.results == []
    assert arxiv.calls == 0


@pytest.mark.parametrize(
    "error, reason",
    [(S2TransientError("s2_rate_limited"), "s2_rate_limited"),
     (S2TransientError("s2_timeout"), "s2_timeout"),
     (S2AuthError("bad key"), "s2_auth_error")],
)
async def test_falls_back_to_arxiv_on_transient_and_auth_errors(error, reason):
    resp = await SearchService(FakeS2(error=error), FakeArxiv()).search("q")
    assert resp.source == "arxiv" and resp.fallback_reason == reason
    assert resp.results[0].title == "From arXiv"


async def test_bad_request_is_raised_not_masked_by_fallback():
    arxiv = FakeArxiv()
    with pytest.raises(SearchBadRequest):
        await SearchService(FakeS2(error=S2BadRequest("bad query")), arxiv).search("q")
    assert arxiv.calls == 0


@pytest.mark.parametrize("arxiv_error", [httpx.ConnectError("down"), ET.ParseError("bad xml")])
async def test_both_sources_failing_raises_unavailable(arxiv_error):
    with pytest.raises(SearchUnavailable, match="s2_timeout"):
        await SearchService(FakeS2(error=S2TransientError("s2_timeout")), FakeArxiv(arxiv_error)).search("q")
