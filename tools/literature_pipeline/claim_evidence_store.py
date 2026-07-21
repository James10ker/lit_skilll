from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .schema import ACCESS_POLICIES, AccessLevel, Claim, Evidence, Paper


RELATIONS = {"supports", "partially_supports", "contradicts", "uncertain"}
CONFIDENCES = {"high", "medium", "low"}
SUPPORT_STATUSES = {"verified", "partial", "contradicted", "insufficient", "unverified"}
CLAIM_MINIMUM_ACCESS = {
    "existence": "metadata_only",
    "bibliographic": "metadata_only",
    "publication_statistics": "metadata_only",
    "background": "abstract_only",
    "direction_existence": "abstract_only",
    "research_question": "abstract_only",
    "coarse_method": "abstract_only",
    "abstract_finding": "abstract_only",
    "method_detail": "section_level",
    "experimental_result": "section_level",
    "performance_number": "section_level",
    "limitation": "section_level",
    "comparison": "section_level",
    "future_direction": "section_level",
    "causal": "fulltext",
    "field_consensus": "section_level",
}
SECTION_REQUIREMENTS = {
    "method_detail": {"method", "methods", "methodology"},
    "experimental_result": {"experiment", "experiments", "results", "evaluation"},
    "performance_number": {"experiment", "experiments", "results", "evaluation"},
    "limitation": {"limitation", "limitations", "discussion"},
    "future_direction": {"discussion", "conclusion", "conclusions", "future work"},
}


def _load_papers(path: Path) -> dict[str, Paper]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("papers", payload.get("records", payload)) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError("paper store must contain a papers list")
    return {paper.paper_id: paper for item in raw if isinstance(item, dict) for paper in [Paper.from_dict(item)]}


def validate_store(ledger_path: Path, paper_store_path: Path) -> dict[str, Any]:
    papers = _load_papers(paper_store_path)
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    claims = payload.get("claims", payload) if isinstance(payload, dict) else payload
    errors: list[str] = []
    warnings: list[str] = []
    verified_claims = 0
    if not isinstance(claims, list):
        return {"passed": False, "errors": ["ledger must contain a claims list"], "warnings": [], "metrics": {"claim_count": 0}}
    seen: set[str] = set()
    for index, raw_claim in enumerate(claims, start=1):
        label = str(raw_claim.get("claim_id") or f"#{index}") if isinstance(raw_claim, dict) else f"#{index}"
        if not isinstance(raw_claim, dict):
            errors.append(f"Claim {label} is not an object.")
            continue
        if label in seen:
            errors.append(f"Duplicate claim_id: {label}")
        seen.add(label)
        claim_type = str(raw_claim.get("claim_type") or "").strip()
        strength = str(raw_claim.get("strength") or "").strip()
        status = str(raw_claim.get("support_status") or "unverified").strip()
        evidence_items = raw_claim.get("evidence")
        if not str(raw_claim.get("text") or raw_claim.get("claim") or "").strip():
            errors.append(f"Claim {label} has no text.")
        if claim_type not in CLAIM_MINIMUM_ACCESS:
            errors.append(f"Claim {label} has unknown claim_type: {claim_type or '<missing>'}")
        if strength not in {"descriptive", "moderate", "strong"}:
            errors.append(f"Claim {label} has invalid strength: {strength or '<missing>'}")
        if status not in SUPPORT_STATUSES:
            errors.append(f"Claim {label} has invalid support_status: {status}")
        if not isinstance(evidence_items, list) or not evidence_items:
            errors.append(f"Claim {label} has no evidence objects.")
            continue
        positive = 0
        distinct_papers: set[str] = set()
        for ev_index, evidence in enumerate(evidence_items, start=1):
            if not isinstance(evidence, dict):
                errors.append(f"Claim {label} evidence #{ev_index} is not an object.")
                continue
            paper_id = str(evidence.get("paper_id") or "")
            paper = papers.get(paper_id)
            relation = str(evidence.get("relation") or "")
            access = str(evidence.get("access_level") or "")
            if paper is None:
                errors.append(f"Claim {label} references unknown paper_id: {paper_id or '<missing>'}")
                continue
            distinct_papers.add(paper_id)
            if access != paper.access_level:
                errors.append(f"Claim {label} evidence access {access or '<missing>'} does not match paper store access {paper.access_level} for {paper_id}.")
            if relation not in RELATIONS:
                errors.append(f"Claim {label} has invalid evidence relation: {relation or '<missing>'}")
            if str(evidence.get("confidence") or "") not in CONFIDENCES:
                errors.append(f"Claim {label} evidence for {paper_id} has invalid confidence.")
            if bool(evidence.get("existence_verified")) != paper.existence_verified:
                errors.append(f"Claim {label} existence_verified disagrees with paper store for {paper_id}.")
            minimum = CLAIM_MINIMUM_ACCESS.get(claim_type, "fulltext")
            if access in AccessLevel.__members__ and AccessLevel[access] < AccessLevel[minimum]:
                errors.append(f"Claim {label} of type {claim_type} requires {minimum}, but {paper_id} is only {access}.")
            allowed = ACCESS_POLICIES.get(access, ())
            if claim_type not in allowed and "*" not in allowed:
                errors.append(f"Claim {label} type {claim_type} is not allowed by {paper_id}'s usage policy.")
            required_sections = SECTION_REQUIREMENTS.get(claim_type)
            section = str(evidence.get("source_section") or "").casefold()
            if required_sections and not any(term in section for term in required_sections):
                errors.append(f"Claim {label} requires a matching source section for {claim_type}; got {section or '<missing>'}.")
            if claim_type == "performance_number" and not (evidence.get("table_id") or evidence.get("page") is not None or evidence.get("paragraph_id")):
                errors.append(f"Claim {label} reports a performance number without a table/page/paragraph locator.")
            if relation in {"supports", "partially_supports"} and bool(evidence.get("claim_supported")):
                positive += 1
        if claim_type == "field_consensus" and len(distinct_papers) < 3:
            errors.append(f"Claim {label} asserts field consensus with fewer than three distinct papers.")
        if status == "verified" and positive == 0:
            errors.append(f"Claim {label} is marked verified but has no supporting evidence marked claim_supported=true.")
        if status == "verified" and positive:
            verified_claims += 1
        elif status == "unverified":
            warnings.append(f"Claim {label} remains unverified and must not enter the manuscript as established fact.")
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {"claim_count": len(claims), "verified_claim_count": verified_claims, "paper_count": len(papers)},
    }


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": "2.0", "claims": []}
