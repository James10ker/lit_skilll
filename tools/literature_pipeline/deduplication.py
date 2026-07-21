from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from typing import Iterable

from .normalization import normalize_arxiv_id, normalize_author, normalize_doi, normalize_title
from .schema import Paper, stable_id


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def _same_fallback_work(left: Paper, right: Paper) -> bool:
    lt, rt = normalize_title(left.title), normalize_title(right.title)
    if not lt or not rt or SequenceMatcher(None, lt, rt).ratio() < 0.94:
        return False
    if left.year and right.year and abs(left.year - right.year) > 2:
        return False
    la = {normalize_author(item) for item in left.authors if item}
    ra = {normalize_author(item) for item in right.authors if item}
    return bool(la & ra) or not la or not ra


def _citation_score(paper: Paper) -> tuple[int, int, int, int, int]:
    kind = paper.document_type.casefold()
    formal = 2 if any(token in kind for token in ("journal", "article")) else 1 if "conference" in kind else 0
    verified = int(paper.existence_verified)
    identifiers = int(bool(normalize_doi(paper.doi))) + int(bool(normalize_arxiv_id(paper.arxiv_id)))
    access = {"metadata_only": 0, "abstract_only": 1, "section_level": 2, "fulltext": 3}.get(paper.access_level, 0)
    return formal, verified, identifiers, access, paper.year or 0


def _citation_key(paper: Paper) -> str:
    author = normalize_author(paper.authors[0]).split()[-1] if paper.authors and normalize_author(paper.authors[0]) else "work"
    title_token = next((token for token in normalize_title(paper.title).split() if len(token) > 3), "paper")
    return f"{author}{paper.year or 'nd'}{title_token}".replace(" ", "")


def merge_versions(papers: Iterable[Paper]) -> list[Paper]:
    items = list(papers)
    uf = UnionFind(len(items))
    indices: dict[tuple[str, str], int] = {}
    for index, paper in enumerate(items):
        for kind, value in (("doi", normalize_doi(paper.doi)), ("arxiv", normalize_arxiv_id(paper.arxiv_id))):
            if not value:
                continue
            key = kind, value
            if key in indices:
                uf.union(index, indices[key])
            else:
                indices[key] = index
    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if uf.find(left) != uf.find(right) and _same_fallback_work(items[left], items[right]):
                uf.union(left, right)

    groups: dict[int, list[Paper]] = defaultdict(list)
    for index, paper in enumerate(items):
        groups[uf.find(index)].append(paper)

    merged: list[Paper] = []
    for group in groups.values():
        citation = max(group, key=_citation_score)
        readable = max(group, key=lambda paper: ({"metadata_only": 0, "abstract_only": 1, "section_level": 2, "fulltext": 3}.get(paper.access_level, 0), _citation_score(paper)))
        identity = normalize_doi(citation.doi) or normalize_arxiv_id(citation.arxiv_id) or normalize_title(citation.title)
        work_id = stable_id("work", identity)
        citation.work_id = work_id
        citation.citation_key = citation.citation_key or _citation_key(citation)
        citation.citation_version_paper_id = citation.paper_id
        citation.read_version_paper_id = readable.paper_id
        citation.versions = [
            {
                "paper_id": item.paper_id,
                "title": item.title,
                "year": item.year,
                "doi": normalize_doi(item.doi),
                "arxiv_id": normalize_arxiv_id(item.arxiv_id),
                "document_type": item.document_type,
                "access_level": item.access_level,
                "url": item.url,
            }
            for item in sorted(group, key=_citation_score, reverse=True)
        ]
        citation.retrieval_sources = sorted({source for item in group for source in item.retrieval_sources})
        if not citation.abstract:
            citation.abstract = next((item.abstract for item in group if item.abstract), "")
        citation.access_level = readable.access_level
        citation.accessed_content = list(readable.accessed_content)
        citation.fulltext_source = readable.fulltext_source
        citation.fulltext_format = readable.fulltext_format
        citation.finalize_policy()
        merged.append(citation)
    return sorted(merged, key=lambda paper: ((paper.year or 0), paper.title.casefold()), reverse=True)
