from __future__ import annotations

import math
import re
from collections import Counter

from .normalization import normalize_author, normalize_title
from .schema import Paper


METHOD_TERMS = {"method", "model", "dataset", "experiment", "evaluation", "sample", "participants", "benchmark", "analysis"}


def _tokens(value: str) -> set[str]:
    return {token for token in normalize_title(value).split() if len(token) >= 3}


def score_paper(paper: Paper, *, query: str, min_year: int | None, max_year: int | None) -> dict[str, float]:
    query_tokens = _tokens(query)
    text_tokens = _tokens(" ".join((paper.title, paper.abstract, " ".join(paper.keywords))))
    relevance = len(query_tokens & text_tokens) / max(1, len(query_tokens))
    date_fit = 1.0 if paper.year and (min_year is None or paper.year >= min_year) and (max_year is None or paper.year <= max_year) else 0.0
    transparency = min(1.0, len(METHOD_TERMS & text_tokens) / 3)
    source_quality = 1.0 if paper.source and paper.document_type not in {"", "posted-content"} else 0.4 if paper.source else 0.0
    citations = max(0, paper.citation_count or 0)
    classicity = min(1.0, math.log1p(citations) / math.log(501))
    recency = 0.0 if not paper.year else max(0.0, min(1.0, (paper.year - 2000) / 25))
    total = 0.42 * relevance + 0.14 * date_fit + 0.13 * transparency + 0.12 * source_quality + 0.08 * classicity + 0.11 * recency
    return {"relevance": round(relevance, 4), "date_fit": date_fit, "method_transparency": round(transparency, 4), "source_quality": source_quality, "classicity": round(classicity, 4), "recency": round(recency, 4), "rule_total": round(total, 4)}


def screen_papers(
    papers: list[Paper], *, query: str, target: int = 100, min_year: int | None = None,
    max_year: int | None = None, min_relevance: float = 0.15, max_per_source: int = 25,
    max_per_first_author: int = 8,
) -> tuple[list[Paper], dict[str, object]]:
    for paper in papers:
        paper.screening_scores = score_paper(paper, query=query, min_year=min_year, max_year=max_year)
        paper.screening_decision = "pending_semantic_review"
        paper.screening_reasons = []
        if not paper.title or not paper.authors:
            paper.screening_decision = "excluded"
            paper.screening_reasons.append("missing title or authors")
        elif paper.screening_scores["date_fit"] == 0:
            paper.screening_decision = "excluded"
            paper.screening_reasons.append("outside requested year range or year missing")
        elif paper.screening_scores["relevance"] < min_relevance:
            paper.screening_decision = "excluded"
            paper.screening_reasons.append("low deterministic title/abstract relevance; review before override")
    candidates = sorted((paper for paper in papers if paper.screening_decision != "excluded"), key=lambda item: item.screening_scores["rule_total"], reverse=True)
    source_counts: Counter[str] = Counter()
    author_counts: Counter[str] = Counter()
    included: list[Paper] = []
    for paper in candidates:
        source = paper.source.casefold() or "<missing>"
        first_author = normalize_author(paper.authors[0]) if paper.authors else "<missing>"
        if source_counts[source] >= max_per_source:
            paper.screening_decision = "diversity_hold"
            paper.screening_reasons.append("source diversity cap reached")
            continue
        if author_counts[first_author] >= max_per_first_author:
            paper.screening_decision = "diversity_hold"
            paper.screening_reasons.append("first-author/team diversity cap reached")
            continue
        paper.screening_decision = "included_rule_stage"
        paper.screening_reasons.append("passed deterministic filters; requires model semantic confirmation")
        included.append(paper)
        source_counts[source] += 1
        author_counts[first_author] += 1
        if len(included) >= target:
            break
    report = {
        "input_count": len(papers), "rule_stage_included_count": len(included),
        "excluded_count": sum(item.screening_decision == "excluded" for item in papers),
        "diversity_hold_count": sum(item.screening_decision == "diversity_hold" for item in papers),
        "semantic_review_required": True,
        "warning": "Rule-stage inclusion is not final. Confirm research population, method fit, quality, and thematic diversity semantically and preserve the reason.",
    }
    return papers, report
