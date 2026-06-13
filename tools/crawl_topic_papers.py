#!/usr/bin/env python3
"""Search and download topic-related papers from public metadata sources.

This script uses OpenAlex search to collect topic-related paper metadata, ranks
results locally for topical relevance, and optionally downloads openly exposed
PDFs. It does not bypass paywalls, logins, captchas, or publisher restrictions.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = "literature-review-skill/0.1 (+topic crawl; no paywall bypass)"
SPACE_RE = re.compile(r"\s+")

AI_TERMS = [
    "artificial intelligence",
    "machine learning",
    "intelligent tutoring",
    "intelligent tutor",
    "intelligent tutoring system",
    "educational data mining",
    "learning analytics",
    "knowledge tracing",
    "neural network",
    "natural language processing",
    "chatbot",
    "expert system",
    "intelligent agent",
    "adaptive learning",
]

EDU_TERMS = [
    "education",
    "educational",
    "learning",
    "teaching",
    "student",
    "students",
    "classroom",
    "school",
    "university",
    "course",
    "curriculum",
    "tutor",
    "tutoring",
]

AIED_QUERIES = [
    "artificial intelligence in education",
    "machine learning education",
    "intelligent tutoring system",
    "educational data mining",
    "chatbot education",
    "natural language processing education",
]


@dataclass
class QueryLog:
    query: str
    work_type: str
    fetched: int = 0
    kept: int = 0


@dataclass
class PaperRecord:
    title: str
    publication_year: int
    work_type: str
    source_name: str = ""
    openalex_id: str = ""
    doi: str = ""
    landing_page_url: str = ""
    oa_url: str = ""
    pdf_url: str = ""
    is_oa: bool = False
    cited_by_count: int = 0
    relevance_score: float = 0.0
    matched_queries: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    abstract: str = ""
    downloaded_pdf: str = ""
    error: str = ""


def _request_json(url: str, *, timeout: int = 12, attempts: int = 2) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(1.0 + attempt * 1.5)
    raise last_error or RuntimeError(f"request failed: {url}")


def _request_bytes(
    url: str,
    *,
    timeout: int = 15,
    max_bytes: int = 80_000_000,
    attempts: int = 2,
) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout) as resp:
                ctype = resp.headers.get("content-type", "")
                data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(f"file too large (> {max_bytes} bytes)")
            return data, ctype
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(1.0 + attempt * 1.5)
    raise last_error or RuntimeError(f"request failed: {url}")


def _clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", (text or "").strip())


def _abstract_from_inverted_index(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    size = max((max(pos) for pos in inv.values() if pos), default=-1) + 1
    if size <= 0:
        return ""
    words = [""] * size
    for token, positions in inv.items():
        for pos in positions:
            if 0 <= pos < size:
                words[pos] = token
    return _clean_text(" ".join(words))


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _score_text(text: str, terms: list[str], weight: float) -> float:
    hay = (text or "").lower()
    return sum(weight for term in terms if term in hay)


def _is_topic_relevant(title: str, abstract: str, source_name: str) -> bool:
    title_l = title.lower()
    abstract_l = abstract.lower()
    source_l = source_name.lower()
    blob = " ".join([title_l, abstract_l, source_l])
    ai_hits = sum(1 for term in AI_TERMS if term in blob)
    edu_title_hits = sum(1 for term in EDU_TERMS if term in title_l or term in source_l)
    source_hit = "artificial intelligence in education" in source_l
    tutoring_hit = any(term in title_l for term in ["tutor", "tutoring", "educational data mining"])
    return source_hit or (ai_hits >= 1 and edu_title_hits >= 1) or (tutoring_hit and ai_hits >= 1)


def _score_work(item: dict[str, Any], matched_query: str) -> tuple[float, str]:
    title = _clean_text(item.get("title", ""))
    abstract = _abstract_from_inverted_index(item.get("abstract_inverted_index"))
    source_name = _clean_text(
        ((item.get("primary_location") or {}).get("source") or {}).get("display_name", "")
    )
    blob = " ".join([title, abstract, source_name])
    score = 0.0
    score += _score_text(title, AI_TERMS, 5.0)
    score += _score_text(title, EDU_TERMS, 3.0)
    score += _score_text(abstract, AI_TERMS, 1.5)
    score += _score_text(abstract, EDU_TERMS, 1.0)
    score += _score_text(source_name, ["artificial intelligence in education"], 8.0)
    score += _score_text(blob, [matched_query.lower()], 4.0)
    score += min(item.get("cited_by_count", 0), 500) / 100.0
    if item.get("type") == "article":
        score += 1.5
    if item.get("open_access", {}).get("is_oa"):
        score += 2.0
    return score, abstract


def _safe_filename(text: str, max_len: int = 100) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return (text[:max_len].strip("_") or "paper") + ".pdf"


def _best_pdf_url(record: PaperRecord) -> str:
    return record.pdf_url or record.oa_url


def fetch_openalex_query(query: str, work_type: str, per_page: int) -> dict[str, Any]:
    params = {
        "search": query,
        "per-page": per_page,
        "filter": ",".join(
            [
                "from_publication_date:2000-01-01",
                "to_publication_date:2026-12-31",
                "language:en",
                f"type:{work_type}",
            ]
        ),
    }
    return _request_json("https://api.openalex.org/works?" + urlencode(params))


def build_records(per_query: int) -> tuple[list[PaperRecord], list[QueryLog]]:
    by_key: dict[str, PaperRecord] = {}
    query_logs: list[QueryLog] = []

    for query in AIED_QUERIES:
        for work_type in ("article", "proceedings-article"):
            log = QueryLog(query=query, work_type=work_type)
            query_logs.append(log)
            print(f"QUERY {query!r} [{work_type}]")
            try:
                data = fetch_openalex_query(query, work_type, per_query)
            except Exception as exc:
                print(f"SKIP {query!r} [{work_type}] {exc}")
                continue
            results = data.get("results") or []
            log.fetched = len(results)
            for item in results:
                title = _clean_text(item.get("title", ""))
                if not title:
                    continue
                score, abstract = _score_work(item, query)
                source_name = _clean_text(
                    ((item.get("primary_location") or {}).get("source") or {}).get("display_name", "")
                )
                if not _is_topic_relevant(title, abstract, source_name):
                    continue
                log.kept += 1
                doi = (item.get("doi") or "").replace("https://doi.org/", "")
                oa = item.get("open_access") or {}
                primary = item.get("primary_location") or {}
                pdf_url = primary.get("pdf_url", "") or oa.get("oa_url", "")
                authors = [
                    _clean_text((author.get("author") or {}).get("display_name", ""))
                    for author in item.get("authorships") or []
                    if (author.get("author") or {}).get("display_name")
                ]
                concepts = [
                    _clean_text(concept.get("display_name", ""))
                    for concept in item.get("concepts") or []
                    if concept.get("display_name")
                ]
                key = doi.lower() or item.get("id", "") or _normalize_key(title)
                existing = by_key.get(key)
                if existing:
                    existing.relevance_score = max(existing.relevance_score, score)
                    if query not in existing.matched_queries:
                        existing.matched_queries.append(query)
                    if not existing.pdf_url:
                        existing.pdf_url = pdf_url
                    if not existing.oa_url:
                        existing.oa_url = oa.get("oa_url", "")
                    existing.is_oa = existing.is_oa or bool(oa.get("is_oa"))
                    existing.cited_by_count = max(existing.cited_by_count, item.get("cited_by_count", 0))
                    continue

                by_key[key] = PaperRecord(
                    title=title,
                    publication_year=int(item.get("publication_year") or 0),
                    work_type=item.get("type", work_type),
                    source_name=source_name,
                    openalex_id=item.get("id", ""),
                    doi=doi,
                    landing_page_url=item.get("doi") or item.get("id", ""),
                    oa_url=oa.get("oa_url", ""),
                    pdf_url=pdf_url,
                    is_oa=bool(oa.get("is_oa")),
                    cited_by_count=int(item.get("cited_by_count") or 0),
                    relevance_score=score,
                    matched_queries=[query],
                    authors=authors,
                    concepts=concepts,
                    abstract=abstract,
                )

    records = sorted(
        by_key.values(),
        key=lambda r: (
            r.relevance_score,
            r.cited_by_count,
            r.publication_year,
            r.title.lower(),
        ),
        reverse=True,
    )
    return records, query_logs


def download_pdf(index: int, record: PaperRecord, papers_dir: Path) -> None:
    url = _best_pdf_url(record)
    if not url:
        return
    papers_dir.mkdir(parents=True, exist_ok=True)
    out = papers_dir / f"{index:03d}_{_safe_filename(record.title)}"
    if out.exists():
        record.downloaded_pdf = str(out)
        return
    try:
        data, ctype = _request_bytes(url)
        if b"%PDF" not in data[:1024] and "pdf" not in ctype.lower():
            record.error = f"open PDF URL did not return a PDF: {url}"
            return
        out.write_bytes(data)
        record.downloaded_pdf = str(out)
    except Exception as exc:
        record.error = f"pdf download failed: {exc}"


def write_outputs(records: list[PaperRecord], query_logs: list[QueryLog], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    papers_json = output_dir / "papers.json"
    papers_csv = output_dir / "papers.csv"
    papers_md = output_dir / "papers.md"
    search_log_json = output_dir / "search_log.json"

    papers_json.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    search_log_json.write_text(
        json.dumps([asdict(q) for q in query_logs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = list(asdict(records[0]).keys()) if records else list(PaperRecord("", 0, "").__dict__.keys())
    with papers_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["matched_queries"] = "; ".join(row["matched_queries"])
            row["authors"] = "; ".join(row["authors"])
            row["concepts"] = "; ".join(row["concepts"])
            writer.writerow(row)

    with papers_md.open("w", encoding="utf-8") as f:
        f.write("# Crawled Topic Papers\n\n")
        f.write("| # | Year | Type | Score | Citations | Title | Source | DOI | PDF |\n")
        f.write("|---|------|------|-------|-----------|-------|--------|-----|-----|\n")
        for idx, record in enumerate(records, start=1):
            doi = record.doi
            pdf = record.downloaded_pdf or record.pdf_url or record.oa_url
            f.write(
                f"| {idx} | {record.publication_year} | {record.work_type} | {record.relevance_score:.1f} | "
                f"{record.cited_by_count} | {_md_escape(record.title)} | {_md_escape(record.source_name)} | "
                f"{_md_escape(doi)} | {_md_link(pdf)} |\n"
            )


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _md_link(url: str) -> str:
    if not url:
        return ""
    label = urlparse(url).netloc or "link"
    return f"[{_md_escape(label)}]({url})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Search and download topic-related papers via OpenAlex.")
    parser.add_argument("--output-dir", "-o", type=Path, required=True, help="Output directory.")
    parser.add_argument("--limit", type=int, default=150, help="Number of ranked papers to keep.")
    parser.add_argument("--per-query", type=int, default=100, help="OpenAlex results fetched per query/type.")
    parser.add_argument("--download-open-pdf", action="store_true", help="Download openly exposed PDFs only.")
    parser.add_argument("--max-workers", type=int, default=8, help="Concurrent PDF downloads.")
    args = parser.parse_args()

    records, query_logs = build_records(args.per_query)
    records = records[: args.limit]

    if args.download_open_pdf:
        papers_dir = args.output_dir / "papers"
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as ex:
            futures = {
                ex.submit(download_pdf, idx, record, papers_dir): (idx, record)
                for idx, record in enumerate(records, start=1)
            }
            done = 0
            for future in as_completed(futures):
                idx, record = futures[future]
                future.result()
                done += 1
                status = "pdf" if record.downloaded_pdf else ("url" if _best_pdf_url(record) else "meta")
                with lock:
                    print(f"[{done}/{len(records)}] #{idx} {status} {record.title[:90]}")

    write_outputs(records, query_logs, args.output_dir)
    downloaded = sum(1 for r in records if r.downloaded_pdf)
    with_pdf_url = sum(1 for r in records if _best_pdf_url(r))
    print(f"OUTPUT_DIR={args.output_dir.resolve()}")
    print(f"PAPERS={len(records)}")
    print(f"WITH_PDF_URL={with_pdf_url}")
    print(f"DOWNLOADED={downloaded}")
    print(f"CSV={(args.output_dir / 'papers.csv').resolve()}")
    print(f"JSON={(args.output_dir / 'papers.json').resolve()}")
    print(f"MD={(args.output_dir / 'papers.md').resolve()}")
    print(f"SEARCH_LOG={(args.output_dir / 'search_log.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
