#!/usr/bin/env python3
"""Extract author, affiliation, journal, year, topic, and citation metadata.

Input is the existing paper list under outputs/*/papers.json or papers.csv.
The script enriches each record from OpenAlex when possible because OpenAlex
authorships include institution/affiliation data.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract paper metadata table.")
    parser.add_argument(
        "--input",
        default="outputs/aied_topic_150_final/papers.json",
        help="Input papers file: JSON list or CSV.",
    )
    parser.add_argument(
        "--out-dir",
        default="outputs/aied_topic_150_final/metadata",
        help="Directory for paper_metadata.csv/json.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only process first N records.")
    parser.add_argument("--sleep", type=float, default=0.15, help="Delay between OpenAlex calls.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=2, help="Retry count for OpenAlex calls.")
    parser.add_argument("--email", default="", help="Optional contact email for OpenAlex polite pool.")
    return parser.parse_args()


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON list")
        return [dict(row) for row in data]

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    raise ValueError(f"Unsupported input type: {path.suffix}")


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.strip()


def openalex_api_url(record: dict[str, Any], email: str) -> str | None:
    openalex_id = str(record.get("openalex_id") or "").strip()
    doi = normalize_doi(record.get("doi"))
    if openalex_id:
        work_ref = openalex_id.rsplit("/", 1)[-1] if openalex_id.startswith("https://openalex.org/") else openalex_id
    elif doi:
        work_ref = "https://doi.org/" + doi
    else:
        return None

    url = "https://api.openalex.org/works/" + urllib.parse.quote(work_ref, safe="")
    if email:
        url += "?" + urllib.parse.urlencode({"mailto": email})
    return url


def fetch_json(url: str, *, timeout: float, retries: int, user_agent: str) -> tuple[dict[str, Any] | None, str]:
    last_error = ""
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")), "ok"
        except Exception as exc:  # noqa: BLE001 - batch manifest should record all failures.
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    return None, last_error


def split_semicolon(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def source_name(work: dict[str, Any] | None, record: dict[str, Any]) -> str:
    if work:
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}
        if source.get("display_name"):
            return str(source["display_name"])
    return str(record.get("source_name") or "")


def topics(work: dict[str, Any] | None, record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    if work:
        primary_topic = work.get("primary_topic") or {}
        if primary_topic.get("display_name"):
            values.append(str(primary_topic["display_name"]))
        for topic in work.get("topics") or []:
            if isinstance(topic, dict) and topic.get("display_name"):
                values.append(str(topic["display_name"]))
        for keyword in work.get("keywords") or []:
            if isinstance(keyword, dict) and keyword.get("display_name"):
                values.append(str(keyword["display_name"]))
        for concept in work.get("concepts") or []:
            if isinstance(concept, dict) and concept.get("display_name"):
                values.append(str(concept["display_name"]))
    values.extend(split_semicolon(record.get("concepts")))
    return unique(values)


def author_rows(work: dict[str, Any] | None, record: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    if not work:
        names = split_semicolon(record.get("authors"))
        return names, [{"name": name, "institutions": [], "countries": []} for name in names], []

    author_details: list[dict[str, Any]] = []
    all_institutions: list[str] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        name = str(author.get("display_name") or "").strip()
        if not name:
            continue
        institutions = [
            str(inst.get("display_name")).strip()
            for inst in authorship.get("institutions") or []
            if isinstance(inst, dict) and inst.get("display_name")
        ]
        countries = [
            str(country).strip()
            for country in authorship.get("countries") or []
            if str(country).strip()
        ]
        institutions = unique(institutions)
        all_institutions.extend(institutions)
        author_details.append(
            {
                "name": name,
                "institutions": institutions,
                "countries": unique(countries),
            }
        )

    names = [item["name"] for item in author_details]
    return names, author_details, unique(all_institutions)


def extract_row(index: int, record: dict[str, Any], work: dict[str, Any] | None, status: str) -> dict[str, Any]:
    authors, author_details, institutions = author_rows(work, record)
    topic_values = topics(work, record)
    cited_by = (work or {}).get("cited_by_count", record.get("cited_by_count", ""))
    year = (work or {}).get("publication_year", record.get("publication_year", ""))
    doi = normalize_doi((work or {}).get("doi") or record.get("doi"))
    openalex_id = (work or {}).get("id") or record.get("openalex_id") or ""
    title = (work or {}).get("title") or record.get("title") or ""

    return {
        "index": index,
        "title": title,
        "authors": authors,
        "author_affiliations": author_details,
        "institutions": institutions,
        "journal": source_name(work, record),
        "year": year,
        "topics": topic_values,
        "cited_by_count": cited_by,
        "doi": doi,
        "openalex_id": openalex_id,
        "metadata_status": status,
    }


def csv_value(value: Any) -> str:
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            parts = []
            for item in value:
                institutions = "; ".join(item.get("institutions") or [])
                if institutions:
                    parts.append(f"{item.get('name')}: {institutions}")
                else:
                    parts.append(str(item.get("name") or ""))
            return " | ".join(parts)
        return "; ".join(str(item) for item in value)
    return str(value or "")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = load_records(input_path)
    if args.limit:
        records = records[: args.limit]

    contact = f" ({args.email})" if args.email else ""
    user_agent = f"lit-skill-metadata-extractor/1.0{contact}"

    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        url = openalex_api_url(record, args.email)
        work = None
        status = "local_only"
        if url:
            work, status = fetch_json(url, timeout=args.timeout, retries=args.retries, user_agent=user_agent)
            time.sleep(args.sleep)
        row = extract_row(index, record, work, status)
        rows.append(row)
        print(f"[{index:03d}/{len(records):03d}] {status}: {row['title']}", flush=True)

    json_path = out_dir / "paper_metadata.json"
    csv_path = out_dir / "paper_metadata.csv"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "index",
        "title",
        "authors",
        "author_affiliations",
        "institutions",
        "journal",
        "year",
        "topics",
        "cited_by_count",
        "doi",
        "openalex_id",
        "metadata_status",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})

    enriched = sum(1 for row in rows if row["metadata_status"] == "ok")
    local_only = len(rows) - enriched
    print(f"Done: {len(rows)} rows, {enriched} enriched from OpenAlex, {local_only} local fallback.")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
