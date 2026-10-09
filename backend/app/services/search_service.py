"""Paper search: Semantic Scholar first, arXiv only when S2 is unavailable.

Fallback rules (see ARCHITECTURE.md):
  * 429 / 5xx / timeout / network error after retries -> arXiv, fallback_reason set
  * 401 / 403 (bad key)                                -> arXiv, logged WARNING, fallback_reason="s2_auth_error"
  * 400 (malformed query)                              -> raised as SearchBadRequest, no fallback
  * empty S2 result set                                -> returned as-is (it's a valid answer)
"""
import logging
import re
import xml.etree.ElementTree as ET

import httpx

from ..models import PaperMeta, SearchResponse, SearchResult
from .s2_client import S2AuthError, S2BadRequest, S2Client, S2TransientError

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"


class SearchBadRequest(Exception):
    pass


class SearchUnavailable(Exception):
    """Both S2 and the arXiv fallback failed."""


def s2_to_meta(item: dict) -> PaperMeta:
    oa = item.get("openAccessPdf") or {}
    ext = item.get("externalIds") or {}
    pdf_url = oa.get("url") or None
    if not pdf_url and ext.get("ArXiv"):
        pdf_url = f"https://arxiv.org/pdf/{ext['ArXiv']}"
    return PaperMeta(
        source="semantic_scholar",
        external_id=item.get("paperId"),
        title=(item.get("title") or "Untitled").strip(),
        authors=[a.get("name", "") for a in item.get("authors") or [] if a.get("name")],
        year=item.get("year"),
        abstract=item.get("abstract"),
        url=item.get("url"),
        pdf_url=pdf_url,
    )


class ArxivClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        user_agent: str = "ResearchAssistant/0.1",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.user_agent = user_agent
        self._transport = transport

    async def search(self, query: str, limit: int = 20) -> list[PaperMeta]:
        # arXiv ORs bare terms together; AND them so results match the whole query.
        terms = [re.sub(r"[^\w\-]", "", t) for t in query.split()]
        search_query = " AND ".join(f"all:{t}" for t in terms if t) or "all:*"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport, follow_redirects=True
        ) as client:
            resp = await client.get(self.base_url, params=params, headers={"User-Agent": self.user_agent})
            resp.raise_for_status()
        return parse_arxiv_feed(resp.text)


def parse_arxiv_feed(xml_text: str) -> list[PaperMeta]:
    root = ET.fromstring(xml_text)
    results = []
    for entry in root.findall(f"{ATOM}entry"):
        abs_url = (entry.findtext(f"{ATOM}id") or "").strip()
        arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", abs_url)
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
        published = entry.findtext(f"{ATOM}published") or ""
        pdf_url = None
        for link in entry.findall(f"{ATOM}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
        results.append(
            PaperMeta(
                source="arxiv",
                external_id=f"arXiv:{arxiv_id}" if arxiv_id else None,
                title=" ".join((entry.findtext(f"{ATOM}title") or "Untitled").split()),
                authors=[
                    (a.findtext(f"{ATOM}name") or "").strip()
                    for a in entry.findall(f"{ATOM}author")
                ],
                year=int(published[:4]) if published[:4].isdigit() else None,
                abstract=" ".join((entry.findtext(f"{ATOM}summary") or "").split()) or None,
                url=abs_url or None,
                pdf_url=pdf_url or (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None),
            )
        )
    return results


class SearchService:
    def __init__(self, s2: S2Client, arxiv: ArxivClient):
        self.s2 = s2
        self.arxiv = arxiv

    async def search(self, query: str, limit: int = 20) -> SearchResponse:
        try:
            items = await self.s2.search(query, limit)
            return SearchResponse(
                source="semantic_scholar",
                results=[SearchResult(**s2_to_meta(i).model_dump()) for i in items],
            )
        except S2BadRequest as exc:
            raise SearchBadRequest(str(exc)) from exc
        except S2AuthError as exc:
            log.warning("Semantic Scholar rejected the API key; falling back to arXiv: %s", exc)
            reason = "s2_auth_error"
        except S2TransientError as exc:
            log.info("Semantic Scholar unavailable (%s); falling back to arXiv", exc.reason)
            reason = exc.reason

        try:
            papers = await self.arxiv.search(query, limit)
        except (httpx.HTTPError, ET.ParseError) as exc:
            raise SearchUnavailable(f"S2 failed ({reason}) and arXiv failed ({exc})") from exc
        return SearchResponse(
            source="arxiv",
            fallback_reason=reason,
            results=[SearchResult(**p.model_dump()) for p in papers],
        )
