#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from literature_pipeline.claim_evidence_store import validate_store
from literature_pipeline.citation_verification import verify_manuscript
from literature_pipeline.deduplication import merge_versions
from literature_pipeline.document_parser import parse_document
from literature_pipeline.evidence_extraction import find_evidence_candidates
from literature_pipeline.fulltext_retrieval import discover_candidates, download_candidate
from literature_pipeline.retrieval_adapters import ADAPTERS
from literature_pipeline.schema import Paper
from literature_pipeline.screening import screen_papers


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_papers(path: Path) -> list[Paper]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("papers", payload.get("records", payload)) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError("input must be a list or an object with papers/records")
    return [Paper.from_dict(item) for item in raw if isinstance(item, dict)]


def cmd_search(args: argparse.Namespace) -> int:
    papers: list[Paper] = []
    failures: list[dict[str, str]] = []
    per_source = max(1, (args.limit + len(args.sources) - 1) // len(args.sources))
    for name in args.sources:
        try:
            papers.extend(ADAPTERS[name](mailto=args.mailto, timeout=args.timeout).search(args.query, limit=per_source))
        except Exception as exc:
            failures.append({"source": name, "error": f"{type(exc).__name__}: {exc}"})
    merged = merge_versions(papers)
    _write(args.output, {
        "schema_version": "1.0",
        "query": args.query,
        "requested_limit": args.limit,
        "sources": args.sources,
        "raw_record_count": len(papers),
        "work_count": len(merged),
        "source_failures": failures,
        "papers": [paper.to_dict() for paper in merged],
    })
    return 0 if merged else 1


def cmd_deduplicate(args: argparse.Namespace) -> int:
    source = _read_papers(args.input)
    merged = merge_versions(source)
    _write(args.output, {"schema_version": "1.0", "raw_record_count": len(source), "work_count": len(merged), "papers": [paper.to_dict() for paper in merged]})
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    papers, report = screen_papers(_read_papers(args.input), query=args.query, target=args.target, min_year=args.min_year, max_year=args.max_year, min_relevance=args.min_relevance, max_per_source=args.max_per_source, max_per_first_author=args.max_per_first_author)
    _write(args.output, {"schema_version": "1.0", "screening_report": report, "papers": [paper.to_dict() for paper in papers]})
    return 0 if report["rule_stage_included_count"] else 1


def cmd_parse(args: argparse.Namespace) -> int:
    document = parse_document(args.input, paper_id=args.paper_id, source_url=args.source_url, format_hint=args.format)
    _write(args.output, document.to_dict())
    return 0 if document.access_level in {"section_level", "fulltext"} else 1


def cmd_fetch_fulltext(args: argparse.Namespace) -> int:
    papers = {paper.paper_id: paper for paper in _read_papers(args.paper_store)}
    paper = papers.get(args.paper_id)
    if paper is None:
        raise ValueError(f"paper_id not found: {args.paper_id}")
    attempts: list[dict[str, str]] = []
    best = None
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(discover_candidates(paper), start=1):
        if candidate.format == "atom":
            continue
        raw_path, error = download_candidate(candidate, args.raw_dir / f"{paper.paper_id}-{index}", timeout=args.timeout)
        attempts.append({"url": candidate.url, "format": candidate.format, "source": candidate.source, "error": error})
        if raw_path is None:
            continue
        document = parse_document(raw_path, paper_id=paper.paper_id, source_url=candidate.url, format_hint=candidate.format)
        if best is None or {"metadata_only": 0, "abstract_only": 1, "section_level": 2, "fulltext": 3}[document.access_level] > {"metadata_only": 0, "abstract_only": 1, "section_level": 2, "fulltext": 3}[best.access_level]:
            best = document
        if document.access_level == "fulltext":
            break
    payload = {
        "paper_id": paper.paper_id,
        "attempts": attempts,
        "document": best.to_dict() if best else None,
        "paper_store_update": {
            "access_level": best.access_level,
            "accessed_content": [str(item.get("title") or "") for item in best.sections if item.get("title")],
            "fulltext_source": best.source_url,
            "fulltext_format": best.source_format,
        } if best else None,
        "failure": "" if best else "No open candidate was successfully parsed; retain the prior access level.",
    }
    _write(args.output, payload)
    return 0 if best and best.access_level in {"section_level", "fulltext"} else 1


def cmd_extract_evidence(args: argparse.Namespace) -> int:
    payload = json.loads(args.document.read_text(encoding="utf-8"))
    document = payload.get("document", payload) if isinstance(payload, dict) else {}
    candidates = find_evidence_candidates(document, query=args.query, sections=args.sections, limit=args.limit)
    _write(args.output, {"query": args.query, "sections": args.sections, "candidate_count": len(candidates), "warning": "Candidates are retrieval hits only. Review the original block before setting claim_supported=true.", "candidates": candidates})
    return 0 if candidates else 1


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_store(args.ledger, args.paper_store)
    _write(args.report, report)
    return 0 if report["passed"] else 1


def cmd_verify_citations(args: argparse.Namespace) -> int:
    report = verify_manuscript(args.input, args.ledger, args.paper_store)
    _write(args.report, report)
    return 0 if report["passed"] else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Structured literature retrieval, normalization, parsing, and evidence validation.")
    sub = root.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search", help="Search academic APIs and merge duplicate work versions.")
    search.add_argument("--query", required=True)
    search.add_argument("--sources", default=["openalex", "crossref"], type=lambda value: [item.strip() for item in value.split(",") if item.strip()])
    search.add_argument("--limit", type=int, default=300)
    search.add_argument("--mailto", default="")
    search.add_argument("--timeout", type=int, default=30)
    search.add_argument("--output", required=True, type=Path)
    search.set_defaults(func=cmd_search)
    dedup = sub.add_parser("deduplicate", help="Normalize identifiers, deduplicate records, and merge work versions.")
    dedup.add_argument("--input", required=True, type=Path)
    dedup.add_argument("--output", required=True, type=Path)
    dedup.set_defaults(func=cmd_deduplicate)
    screen = sub.add_parser("screen", help="Apply deterministic filters and diversity caps before model semantic screening.")
    screen.add_argument("--input", required=True, type=Path)
    screen.add_argument("--query", required=True)
    screen.add_argument("--target", type=int, default=100)
    screen.add_argument("--min-year", type=int)
    screen.add_argument("--max-year", type=int)
    screen.add_argument("--min-relevance", type=float, default=0.15)
    screen.add_argument("--max-per-source", type=int, default=25)
    screen.add_argument("--max-per-first-author", type=int, default=8)
    screen.add_argument("--output", required=True, type=Path)
    screen.set_defaults(func=cmd_screen)
    parse = sub.add_parser("parse", help="Parse JATS/XML, HTML, or a text-readable PDF into FulltextDocument JSON.")
    parse.add_argument("--input", required=True, type=Path)
    parse.add_argument("--paper-id", required=True)
    parse.add_argument("--source-url", default="")
    parse.add_argument("--format", default="")
    parse.add_argument("--output", required=True, type=Path)
    parse.set_defaults(func=cmd_parse)
    fetch = sub.add_parser("fetch-fulltext", help="Discover and parse lawful open full text without bypassing access controls.")
    fetch.add_argument("--paper-store", required=True, type=Path)
    fetch.add_argument("--paper-id", required=True)
    fetch.add_argument("--raw-dir", required=True, type=Path)
    fetch.add_argument("--output", required=True, type=Path)
    fetch.add_argument("--timeout", type=int, default=45)
    fetch.set_defaults(func=cmd_fetch_fulltext)
    extract = sub.add_parser("extract-evidence", help="Rank located FulltextDocument blocks as unverified evidence candidates.")
    extract.add_argument("--document", required=True, type=Path)
    extract.add_argument("--query", required=True)
    extract.add_argument("--sections", default=[], type=lambda value: [item.strip() for item in value.split(",") if item.strip()])
    extract.add_argument("--limit", type=int, default=10)
    extract.add_argument("--output", required=True, type=Path)
    extract.set_defaults(func=cmd_extract_evidence)
    validate = sub.add_parser("validate-evidence", help="Enforce claim permissions against the paper store.")
    validate.add_argument("--ledger", required=True, type=Path)
    validate.add_argument("--paper-store", required=True, type=Path)
    validate.add_argument("--report", required=True, type=Path)
    validate.set_defaults(func=cmd_validate)
    verify = sub.add_parser("verify-citations", help="Audit manuscript citations against verified claims and paper identities.")
    verify.add_argument("--input", required=True, type=Path)
    verify.add_argument("--ledger", required=True, type=Path)
    verify.add_argument("--paper-store", required=True, type=Path)
    verify.add_argument("--report", required=True, type=Path)
    verify.set_defaults(func=cmd_verify_citations)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(sys.argv[1:] if argv is None else argv)
    unknown = [name for name in getattr(args, "sources", []) if name not in ADAPTERS]
    if unknown:
        raise SystemExit(f"unknown retrieval source(s): {', '.join(unknown)}")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
