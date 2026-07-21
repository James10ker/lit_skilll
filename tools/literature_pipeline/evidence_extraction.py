from __future__ import annotations

import re
from typing import Any


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]+", value) if len(token) >= 3}


def find_evidence_candidates(document: dict[str, Any], *, query: str, sections: list[str], limit: int = 10) -> list[dict[str, Any]]:
    """Rank located blocks for human/model review; never declares claim support."""
    query_tokens = _tokens(query)
    section_terms = [item.casefold() for item in sections]
    candidates: list[tuple[float, dict[str, Any]]] = []
    for block in document.get("blocks") or []:
        if not isinstance(block, dict) or not str(block.get("text") or "").strip():
            continue
        section = str(block.get("section") or "")
        if section_terms and not any(term in section.casefold() for term in section_terms):
            continue
        block_tokens = _tokens(str(block.get("text") or ""))
        overlap = len(query_tokens & block_tokens) / max(1, len(query_tokens))
        if overlap <= 0:
            continue
        item = {
            "candidate_id": f"candidate-{block.get('block_id')}",
            "block_id": block.get("block_id"),
            "source_section": section,
            "page": block.get("page"),
            "paragraph_id": str(block.get("paragraph") or block.get("block_id") or ""),
            "table_id": block.get("table_id") or "",
            "excerpt": str(block.get("text") or "")[:800],
            "lexical_score": round(overlap, 4),
            "claim_supported": False,
            "review_status": "candidate_only",
        }
        candidates.append((overlap, item))
    return [item for _, item in sorted(candidates, key=lambda pair: pair[0], reverse=True)[:limit]]
