from __future__ import annotations

import html
import json
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from .normalization import normalize_arxiv_id, normalize_doi
from .schema import Paper, stable_id


def _request_json(url: str, *, user_agent: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _strip_markup(value: str | None) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()


class RetrievalAdapter(ABC):
    name: str

    @abstractmethod
    def search(self, query: str, *, limit: int) -> list[Paper]:
        raise NotImplementedError


class OpenAlexAdapter(RetrievalAdapter):
    name = "openalex"

    def __init__(self, mailto: str = "", timeout: int = 30) -> None:
        self.mailto = mailto
        self.timeout = timeout

    @staticmethod
    def _abstract(index: dict[str, list[int]] | None) -> str:
        if not index:
            return ""
        positions = sorted((position, word) for word, values in index.items() for position in values)
        return " ".join(word for _, word in positions)

    def search(self, query: str, *, limit: int) -> list[Paper]:
        results: list[Paper] = []
        cursor = "*"
        while len(results) < limit and cursor:
            size = min(200, limit - len(results))
            params = {"search": query, "per-page": size, "cursor": cursor}
            if self.mailto:
                params["mailto"] = self.mailto
            url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
            payload = _request_json(url, user_agent=f"literature-review-skill/1.0 ({self.mailto or 'no-email'})", timeout=self.timeout)
            for raw in payload.get("results", []):
                ids = raw.get("ids") or {}
                primary = raw.get("primary_location") or {}
                source = primary.get("source") or {}
                authors = [
                    ((entry.get("author") or {}).get("display_name") or "").strip()
                    for entry in raw.get("authorships") or []
                ]
                doi = normalize_doi(raw.get("doi") or ids.get("doi"))
                arxiv_id = normalize_arxiv_id(ids.get("arxiv"))
                identity = doi or arxiv_id or raw.get("id") or raw.get("title") or str(len(results))
                concepts = [item.get("display_name", "") for item in (raw.get("concepts") or [])[:8] if item.get("display_name")]
                oa = raw.get("open_access") or {}
                results.append(Paper(
                    paper_id=stable_id("paper", f"openalex:{identity}"),
                    work_id="",
                    title=(raw.get("title") or "").strip(),
                    authors=[author for author in authors if author],
                    year=raw.get("publication_year"),
                    source=(source.get("display_name") or "").strip(),
                    doi=doi,
                    arxiv_id=arxiv_id,
                    url=(primary.get("landing_page_url") or raw.get("id") or "").strip(),
                    abstract=self._abstract(raw.get("abstract_inverted_index")),
                    keywords=concepts,
                    topic_tags=concepts,
                    citation_count=raw.get("cited_by_count"),
                    open_access=bool(oa.get("is_oa")),
                    document_type=(raw.get("type") or "").strip(),
                    retrieval_sources=[self.name],
                    access_level="abstract_only" if raw.get("abstract_inverted_index") else "metadata_only",
                    existence_verified=bool(raw.get("id")),
                ))
            cursor = (payload.get("meta") or {}).get("next_cursor")
            if not payload.get("results"):
                break
            time.sleep(0.1)
        return results[:limit]


class CrossrefAdapter(RetrievalAdapter):
    name = "crossref"

    def __init__(self, mailto: str = "", timeout: int = 30) -> None:
        self.mailto = mailto
        self.timeout = timeout

    @staticmethod
    def _year(raw: dict[str, Any]) -> int | None:
        for key in ("published-print", "published-online", "published", "issued", "created"):
            parts = ((raw.get(key) or {}).get("date-parts") or [])
            if parts and parts[0]:
                return int(parts[0][0])
        return None

    def search(self, query: str, *, limit: int) -> list[Paper]:
        params = {"query.bibliographic": query, "rows": min(limit, 1000), "select": "DOI,title,author,published-print,published-online,published,issued,created,container-title,abstract,URL,type,is-referenced-by-count,subject,link"}
        if self.mailto:
            params["mailto"] = self.mailto
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        payload = _request_json(url, user_agent=f"literature-review-skill/1.0 ({self.mailto or 'no-email'})", timeout=self.timeout)
        results: list[Paper] = []
        for raw in (payload.get("message") or {}).get("items", []):
            doi = normalize_doi(raw.get("DOI"))
            title = " ".join(raw.get("title") or []).strip()
            authors = [" ".join(filter(None, (item.get("given"), item.get("family")))).strip() for item in raw.get("author") or []]
            abstract = _strip_markup(raw.get("abstract"))
            links = raw.get("link") or []
            is_open = any("text-mining" in str(item.get("intended-application", "")) for item in links)
            results.append(Paper(
                paper_id=stable_id("paper", f"crossref:{doi or title}"),
                work_id="",
                title=title,
                authors=[author for author in authors if author],
                year=self._year(raw),
                source="; ".join(raw.get("container-title") or []),
                doi=doi,
                url=(raw.get("URL") or "").strip(),
                abstract=abstract,
                keywords=[str(item) for item in raw.get("subject") or []],
                topic_tags=[str(item) for item in raw.get("subject") or []],
                citation_count=raw.get("is-referenced-by-count"),
                open_access=is_open or None,
                document_type=(raw.get("type") or "").strip(),
                retrieval_sources=[self.name],
                access_level="abstract_only" if abstract else "metadata_only",
                existence_verified=bool(doi),
            ))
        return results[:limit]


ADAPTERS = {"openalex": OpenAlexAdapter, "crossref": CrossrefAdapter}
