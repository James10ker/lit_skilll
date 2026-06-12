#!/usr/bin/env python3
"""Extract and enrich papers cited by a review PDF.

The script reads a review PDF, splits its reference list into citation entries,
then queries public metadata APIs to enrich each cited paper. It does not bypass
paywalls, login walls, captchas, or publisher access controls. Optional PDF
downloads are limited to URLs exposed by public metadata or already present in
the reference list.

Examples:
  python3 tools/crawl_review_references.py \\
    --input "../docs/Two Decades of Artificial Intelligence in Education- Contributors, Collaborations, Research Topics, Challenges, and Future Directions.pdf" \\
    --output-dir outputs/aied_reference_crawl

  python3 tools/crawl_review_references.py -i review.pdf -o outputs/crawl \\
    --download-open-pdf --limit 10
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "literature-review-skill/0.1 (+metadata enrichment; no paywall bypass)"
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.I)
URL_RE = re.compile(r"https?://[^\s)>\]]+", re.I)
YEAR_RE = re.compile(r"\((\d{4}[a-z]?)\)")
REFERENCE_START_RE = re.compile(
    r"^[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\- ]+,\s+.+?\(\d{4}[a-z]?\)"
)
PAGE_NUMBER_RE = re.compile(r"^\s*\d+\s*$")
SPACE_RE = re.compile(r"\s+")


@dataclass
class ReferenceRecord:
    index: int
    raw_reference: str
    parsed_title: str = ""
    parsed_year: str = ""
    parsed_doi: str = ""
    parsed_urls: list[str] = field(default_factory=list)
    source: str = "pdf"
    matched_title: str = ""
    matched_year: str = ""
    matched_doi: str = ""
    matched_url: str = ""
    open_pdf_url: str = ""
    metadata_source: str = ""
    confidence: str = "unmatched"
    downloaded_pdf: str = ""
    error: str = ""


def _require_fitz():
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise SystemExit(
            "PyMuPDF is required. Install dependencies with: pip install -r requirements.txt"
        ) from exc
    return fitz


def _clean_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    # PDF extraction cannot reliably distinguish a discretionary line-break
    # hyphen from a meaningful hyphen in a title. A space is safer for metadata
    # search than creating glued tokens such as "firstyear".
    text = re.sub(r"-\n(?=[a-z])", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text


def extract_pdf_text(input_pdf: Path) -> str:
    fitz = _require_fitz()
    doc = fitz.open(input_pdf)
    pages = []
    for page in doc:
        pages.append(page.get_text("text") or "")
    return _clean_text("\n".join(pages))


def _find_reference_text(full_text: str) -> str:
    # Strong signal first: an explicit heading.
    heading = re.search(r"(?im)^\s*(references|bibliography)\s*$", full_text)
    if heading:
        return full_text[heading.end() :]

    # Fallback for PDFs where the reference heading is missing in extracted text:
    # start near the first APA-looking line in the last half of the document.
    lines = full_text.splitlines()
    start_search = max(0, len(lines) // 2)
    for idx in range(start_search, len(lines)):
        line = lines[idx].strip()
        if REFERENCE_START_RE.match(line):
            return "\n".join(lines[idx:])
    return full_text


def split_references(reference_text: str) -> list[str]:
    entries: list[str] = []
    current: list[str] = []

    for raw_line in reference_text.splitlines():
        line = raw_line.strip()
        if not line or PAGE_NUMBER_RE.match(line):
            continue
        if line.lower().startswith(("acknowledgement", "appendix")):
            continue

        starts_new = bool(REFERENCE_START_RE.match(line))
        if starts_new and current:
            entries.append(_normalize_reference(" ".join(current)))
            current = [line]
        else:
            current.append(line)

    if current:
        entries.append(_normalize_reference(" ".join(current)))

    # Remove obvious non-reference tail/head fragments.
    return [e for e in entries if YEAR_RE.search(e) and len(e) >= 40]


def _normalize_reference(text: str) -> str:
    text = SPACE_RE.sub(" ", text).strip()
    text = re.sub(r"https?://doi\.org/", "https://doi.org/", text, flags=re.I)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text


def parse_reference(index: int, raw_reference: str) -> ReferenceRecord:
    record = ReferenceRecord(index=index, raw_reference=raw_reference)
    doi_match = DOI_RE.search(raw_reference)
    if doi_match:
        record.parsed_doi = doi_match.group(0).rstrip(".,;)")

    urls = [u.rstrip(".,;)") for u in URL_RE.findall(raw_reference)]
    record.parsed_urls = list(dict.fromkeys(urls))

    year_match = YEAR_RE.search(raw_reference)
    if year_match:
        record.parsed_year = year_match.group(1)

    record.parsed_title = _guess_title(raw_reference)
    return record


def _guess_title(reference: str) -> str:
    year_match = YEAR_RE.search(reference)
    if not year_match:
        return ""
    rest = reference[year_match.end() :].strip()
    if rest.startswith("."):
        rest = rest[1:].strip()
    rest = re.sub(URL_RE, "", rest)
    rest = re.sub(DOI_RE, "", rest)
    parts = re.split(r"\.\s+", rest)
    title = parts[0].strip(" .")
    # APA titles may contain abbreviations, so if the first chunk is too short,
    # merge one more sentence-sized chunk.
    if len(title) < 25 and len(parts) > 1:
        title = (parts[0] + ". " + parts[1]).strip(" .")
    return SPACE_RE.sub(" ", title)


def _request_json(url: str, *, timeout: int = 25) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _request_bytes(url: str, *, timeout: int = 40, max_bytes: int = 80_000_000) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("content-type", "")
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"file too large (> {max_bytes} bytes)")
    return data, ctype


def enrich_record(record: ReferenceRecord, *, sleep_s: float) -> None:
    if record.parsed_doi:
        if _enrich_crossref_by_doi(record):
            return
        time.sleep(sleep_s)
        if _enrich_openalex(record):
            return

    if record.parsed_title:
        if _enrich_crossref_by_title(record):
            return
        time.sleep(sleep_s)
        if _enrich_semantic_scholar(record):
            return
        time.sleep(sleep_s)
        if _enrich_openalex(record):
            return


def _set_match(
    record: ReferenceRecord,
    *,
    title: str = "",
    year: str = "",
    doi: str = "",
    url: str = "",
    pdf_url: str = "",
    source: str,
    confidence: str,
) -> None:
    record.matched_title = title or record.matched_title
    record.matched_year = str(year or record.matched_year or "")
    record.matched_doi = (doi or record.matched_doi or "").lower()
    record.matched_url = url or record.matched_url
    record.open_pdf_url = pdf_url or record.open_pdf_url
    record.metadata_source = source
    record.confidence = confidence


def _title_similarity(a: str, b: str) -> float:
    def toks(x: str) -> set[str]:
        return {
            t
            for t in re.findall(r"[a-z0-9]+", x.lower())
            if len(t) > 2 and t not in {"the", "and", "for", "with", "using"}
        }

    aa, bb = toks(a), toks(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def _confidence(record: ReferenceRecord, candidate_title: str, candidate_year: str = "") -> str:
    sim = _title_similarity(record.parsed_title, candidate_title)
    year_ok = not record.parsed_year or not candidate_year or record.parsed_year[:4] == str(candidate_year)[:4]
    if sim >= 0.82 and year_ok:
        return "high"
    if sim >= 0.58 and year_ok:
        return "medium"
    return "low"


def _enrich_crossref_by_doi(record: ReferenceRecord) -> bool:
    doi = record.parsed_doi
    try:
        data = _request_json(f"https://api.crossref.org/works/{quote(doi, safe='')}")
        msg = data.get("message", {})
        title = " ".join(msg.get("title") or [])
        year = _crossref_year(msg)
        url = msg.get("URL", "")
        pdf_url = _crossref_pdf_url(msg)
        _set_match(
            record,
            title=title,
            year=year,
            doi=msg.get("DOI", doi),
            url=url,
            pdf_url=pdf_url,
            source="crossref:doi",
            confidence="high",
        )
        return True
    except Exception as exc:
        record.error = f"crossref doi failed: {exc}"
        return False


def _enrich_crossref_by_title(record: ReferenceRecord) -> bool:
    query = urlencode({"query.title": record.parsed_title, "rows": 1})
    try:
        data = _request_json(f"https://api.crossref.org/works?{query}")
        items = data.get("message", {}).get("items", [])
        if not items:
            return False
        item = items[0]
        title = " ".join(item.get("title") or [])
        conf = _confidence(record, title, _crossref_year(item))
        if conf == "low":
            return False
        _set_match(
            record,
            title=title,
            year=_crossref_year(item),
            doi=item.get("DOI", ""),
            url=item.get("URL", ""),
            pdf_url=_crossref_pdf_url(item),
            source="crossref:title",
            confidence=conf,
        )
        return True
    except Exception as exc:
        record.error = f"crossref title failed: {exc}"
        return False


def _crossref_year(item: dict[str, Any]) -> str:
    for key in ("published-print", "published-online", "published", "created", "issued"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def _crossref_pdf_url(item: dict[str, Any]) -> str:
    for link in item.get("link", []) or []:
        url = link.get("URL", "")
        ctype = (link.get("content-type") or "").lower()
        if url and ("pdf" in ctype or url.lower().endswith(".pdf")):
            return url
    return ""


def _enrich_semantic_scholar(record: ReferenceRecord) -> bool:
    fields = "title,year,externalIds,url,openAccessPdf"
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search?"
        + urlencode({"query": record.parsed_title, "limit": 1, "fields": fields})
    )
    try:
        data = _request_json(url)
        rows = data.get("data", [])
        if not rows:
            return False
        item = rows[0]
        title = item.get("title", "")
        conf = _confidence(record, title, str(item.get("year", "")))
        if conf == "low":
            return False
        external = item.get("externalIds") or {}
        pdf = item.get("openAccessPdf") or {}
        _set_match(
            record,
            title=title,
            year=str(item.get("year", "") or ""),
            doi=external.get("DOI", ""),
            url=item.get("url", ""),
            pdf_url=pdf.get("url", "") if isinstance(pdf, dict) else "",
            source="semantic_scholar:title",
            confidence=conf,
        )
        return True
    except Exception as exc:
        record.error = f"semantic scholar failed: {exc}"
        return False


def _enrich_openalex(record: ReferenceRecord) -> bool:
    if record.parsed_doi:
        url = f"https://api.openalex.org/works/https://doi.org/{quote(record.parsed_doi, safe='/')}"
    else:
        url = "https://api.openalex.org/works?" + urlencode(
            {"search": record.parsed_title, "per-page": 1}
        )
    try:
        data = _request_json(url)
        item = data
        if "results" in data:
            results = data.get("results") or []
            if not results:
                return False
            item = results[0]
        title = item.get("title", "")
        conf = "high" if record.parsed_doi else _confidence(record, title, str(item.get("publication_year", "")))
        if conf == "low":
            return False
        oa = item.get("open_access") or {}
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        _set_match(
            record,
            title=title,
            year=str(item.get("publication_year", "") or ""),
            doi=(item.get("doi") or "").replace("https://doi.org/", ""),
            url=item.get("doi") or item.get("id", ""),
            pdf_url=oa.get("oa_url", "") or primary.get("pdf_url", ""),
            source="openalex",
            confidence=conf,
        )
        if not record.matched_url and source.get("homepage_url"):
            record.matched_url = source["homepage_url"]
        return True
    except Exception as exc:
        record.error = f"openalex failed: {exc}"
        return False


def _safe_filename(text: str, max_len: int = 90) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return (text[:max_len].strip("_") or "paper") + ".pdf"


def _best_pdf_url(record: ReferenceRecord) -> str:
    if record.open_pdf_url:
        return record.open_pdf_url
    for url in record.parsed_urls:
        if url.lower().endswith(".pdf") or "/pdf/" in url.lower() or "fulltext" in url.lower():
            return url
    return ""


def download_open_pdf(record: ReferenceRecord, papers_dir: Path) -> None:
    url = _best_pdf_url(record)
    if not url:
        return
    papers_dir.mkdir(parents=True, exist_ok=True)
    stem = record.matched_title or record.parsed_title or f"reference_{record.index:03d}"
    out = papers_dir / f"{record.index:03d}_{_safe_filename(stem)}"
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


def write_outputs(records: list[ReferenceRecord], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "references.json"
    csv_path = output_dir / "references.csv"
    md_path = output_dir / "references.md"
    json_path.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = list(asdict(records[0]).keys()) if records else list(ReferenceRecord(0, "").__dict__.keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["parsed_urls"] = "; ".join(row["parsed_urls"])
            writer.writerow(row)

    with md_path.open("w", encoding="utf-8") as f:
        f.write("# Crawled Review References\n\n")
        f.write("| # | Confidence | Year | Title | DOI | URL | PDF |\n")
        f.write("|---|------------|------|-------|-----|-----|-----|\n")
        for r in records:
            title = r.matched_title or r.parsed_title or "(title not parsed)"
            doi = r.matched_doi or r.parsed_doi
            url = r.matched_url or (r.parsed_urls[0] if r.parsed_urls else "")
            pdf = r.downloaded_pdf or r.open_pdf_url or ""
            f.write(
                f"| {r.index} | {r.confidence} | {r.matched_year or r.parsed_year} | "
                f"{_md_escape(title)} | {_md_escape(doi)} | {_md_link(url)} | {_md_link(pdf)} |\n"
            )


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _md_link(url: str) -> str:
    if not url:
        return ""
    label = urlparse(url).netloc or "link"
    return f"[{_md_escape(label)}]({url})"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract references from a review PDF and crawl public paper metadata."
    )
    parser.add_argument("--input", "-i", type=Path, required=True, help="Review PDF path.")
    parser.add_argument("--output-dir", "-o", type=Path, required=True, help="Output directory.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N references.")
    parser.add_argument("--sleep", type=float, default=0.8, help="Delay between API calls in seconds.")
    parser.add_argument(
        "--download-open-pdf",
        action="store_true",
        help="Download openly exposed PDFs only. This does not bypass access controls.",
    )
    args = parser.parse_args()

    input_pdf = args.input.expanduser().resolve()
    if not input_pdf.is_file():
        print(f"Input PDF not found: {input_pdf}", file=sys.stderr)
        return 2

    output_dir = args.output_dir.expanduser().resolve()
    text = extract_pdf_text(input_pdf)
    reference_text = _find_reference_text(text)
    raw_refs = split_references(reference_text)
    if args.limit > 0:
        raw_refs = raw_refs[: args.limit]

    records = [parse_reference(i + 1, ref) for i, ref in enumerate(raw_refs)]
    papers_dir = output_dir / "papers"
    for record in records:
        print(f"[{record.index}/{len(records)}] {record.parsed_title[:90]}")
        enrich_record(record, sleep_s=max(0.0, args.sleep))
        if args.download_open_pdf:
            download_open_pdf(record, papers_dir)
        time.sleep(max(0.0, args.sleep))

    write_outputs(records, output_dir)
    print(f"OUTPUT_DIR={output_dir}")
    print(f"REFERENCES={len(records)}")
    print(f"CSV={output_dir / 'references.csv'}")
    print(f"JSON={output_dir / 'references.json'}")
    print(f"MD={output_dir / 'references.md'}")
    if args.download_open_pdf:
        print(f"PAPERS_DIR={papers_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
