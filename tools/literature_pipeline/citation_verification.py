from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


CITE = re.compile(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|autocite|parencite|textcite)\*?(?:\[[^\]]*\]){0,2}\{([^}]+)\}")


def _normalize_tex(value: str) -> str:
    value = re.sub(r"%.*", " ", value)
    value = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\[a-zA-Z]+", " ", value)
    value = re.sub(r"[{}~]", " ", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _numbers(value: str) -> set[str]:
    value = CITE.sub(" ", value)
    return set(re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?%?(?![A-Za-z0-9])", value))


def verify_manuscript(tex_path: Path, ledger_path: Path, paper_store_path: Path) -> dict[str, Any]:
    tex = tex_path.read_text(encoding="utf-8")
    normalized_tex = _normalize_tex(tex)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    claims = ledger.get("claims", ledger) if isinstance(ledger, dict) else ledger
    store = json.loads(paper_store_path.read_text(encoding="utf-8"))
    papers = store.get("papers", store.get("records", store)) if isinstance(store, dict) else store
    key_to_paper = {str(item.get("citation_key") or "").strip(): str(item.get("paper_id") or "") for item in papers if isinstance(item, dict) and item.get("citation_key")}
    manuscript_keys = {key.strip() for match in CITE.finditer(tex) for key in match.group(1).split(",") if key.strip()}
    errors: list[str] = []
    warnings: list[str] = []
    audited = 0
    supported_keys: set[str] = set()
    for raw in claims if isinstance(claims, list) else []:
        if not isinstance(raw, dict) or raw.get("support_status") != "verified":
            continue
        claim_id = str(raw.get("claim_id") or "<missing>")
        keys = {str(key).strip() for key in raw.get("citation_keys") or [] if str(key).strip()}
        evidence_papers = {str(item.get("paper_id") or "") for item in raw.get("evidence") or [] if isinstance(item, dict) and item.get("claim_supported") and item.get("relation") in {"supports", "partially_supports"}}
        expected_keys = {key for key, paper_id in key_to_paper.items() if paper_id in evidence_papers}
        if not keys:
            errors.append(f"Verified claim {claim_id} has no citation_keys.")
        if not keys.issubset(expected_keys):
            errors.append(f"Verified claim {claim_id} cites keys not backed by its supporting evidence: {sorted(keys - expected_keys)}")
        supported_keys.update(keys)
        sentence = str(raw.get("manuscript_text") or "").strip()
        if sentence:
            audited += 1
            normalized_sentence = _normalize_tex(sentence)
            if normalized_sentence not in normalized_tex:
                errors.append(f"Verified claim {claim_id} manuscript_text was not found in the LaTeX manuscript.")
            sentence_keys = {key.strip() for match in CITE.finditer(sentence) for key in match.group(1).split(",") if key.strip()}
            if not keys.issubset(sentence_keys):
                errors.append(f"Verified claim {claim_id} does not place all citation keys in its manuscript sentence.")
            evidence_numbers = {number for item in raw.get("evidence") or [] if isinstance(item, dict) for number in _numbers(str(item.get("excerpt") or ""))}
            unsupported_numbers = _numbers(sentence) - evidence_numbers
            if unsupported_numbers and raw.get("claim_type") in {"performance_number", "experimental_result", "publication_statistics"}:
                errors.append(f"Verified claim {claim_id} contains numbers absent from its evidence excerpts: {sorted(unsupported_numbers)}")
        else:
            warnings.append(f"Verified claim {claim_id} has no manuscript_text; semantic placement was not audited.")
    unknown = manuscript_keys - set(key_to_paper)
    if unknown:
        errors.append(f"Manuscript citations are absent from the paper store: {sorted(unknown)}")
    unlinked = manuscript_keys - supported_keys
    if unlinked:
        warnings.append(f"Manuscript citations are not linked to a verified claim: {sorted(unlinked)}")
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {"manuscript_citation_count": len(manuscript_keys), "verified_claim_count": sum(1 for item in claims if isinstance(item, dict) and item.get("support_status") == "verified"), "placement_audited_claim_count": audited},
    }
