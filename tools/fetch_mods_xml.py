#!/usr/bin/env python3
"""Fetch paper metadata and write one MODS XML file per paper.

The script is designed for the paper lists produced under outputs/*/papers.json
or papers.csv. It fetches fresh metadata from Crossref when a DOI is available
and from OpenAlex for every item with an OpenAlex ID, then serializes the merged
record as MODS 3.7 XML.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


MODS_NS = "http://www.loc.gov/mods/v3"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = (
    "http://www.loc.gov/mods/v3 "
    "https://www.loc.gov/standards/mods/v3/mods-3-7.xsd"
)

ET.register_namespace("", MODS_NS)
ET.register_namespace("xsi", XSI_NS)


@dataclass
class FetchResult:
    ok: bool
    status: str
    data: dict[str, Any] | None = None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch MODS XML metadata for a local paper list."
    )
    parser.add_argument(
        "--input",
        default="outputs/aied_topic_150_final/papers.json",
        help="Input papers file: JSON list or CSV.",
    )
    parser.add_argument(
        "--out-dir",
        default="outputs/aied_topic_150_final/mods_xml",
        help="Directory for *.mods.xml files and manifest files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N records, useful for smoke tests.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Delay between network calls in seconds.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retry count per HTTP request.",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Optional contact email for polite API User-Agent strings.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing XML files instead of resuming.",
    )
    return parser.parse_args()


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON list")
        return [dict(item) for item in data]

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    raise ValueError(f"Unsupported input type: {path.suffix}")


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.strip()


def openalex_work_url(record: dict[str, Any], doi: str) -> str | None:
    if record.get("openalex_id"):
        return str(record["openalex_id"]).strip()
    if doi:
        return "https://doi.org/" + doi
    return None


def request_json(url: str, *, timeout: float, retries: int, user_agent: str) -> FetchResult:
    last_error = ""
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status < 200 or response.status >= 300:
                    return FetchResult(False, f"http_{response.status}")
                return FetchResult(True, "ok", json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return FetchResult(False, "not_found", error=str(exc))
            last_error = f"HTTP {exc.code}: {exc.reason}"
        except Exception as exc:  # noqa: BLE001 - keep manifest useful for batch jobs.
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))

    return FetchResult(False, "error", error=last_error)


def fetch_crossref(doi: str, *, timeout: float, retries: int, user_agent: str) -> FetchResult:
    if not doi:
        return FetchResult(False, "missing_doi")
    quoted = urllib.parse.quote(doi, safe="")
    url = f"https://api.crossref.org/works/{quoted}"
    result = request_json(url, timeout=timeout, retries=retries, user_agent=user_agent)
    if result.ok and result.data:
        message = result.data.get("message")
        if isinstance(message, dict):
            result.data = message
    return result


def fetch_openalex(
    work_ref: str | None,
    *,
    timeout: float,
    retries: int,
    user_agent: str,
    email: str,
) -> FetchResult:
    if not work_ref:
        return FetchResult(False, "missing_openalex_ref")

    if work_ref.startswith("https://openalex.org/"):
        work_id = work_ref.rsplit("/", 1)[-1]
        url = f"https://api.openalex.org/works/{urllib.parse.quote(work_id)}"
    else:
        url = "https://api.openalex.org/works/" + urllib.parse.quote(work_ref, safe="")

    if email:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({"mailto": email})

    return request_json(url, timeout=timeout, retries=retries, user_agent=user_agent)


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if item)
    text = str(value).strip()
    return text or None


def first_text(*values: Any) -> str | None:
    for value in values:
        text = text_or_none(value)
        if text:
            return text
    return None


def date_from_parts(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not parts or not isinstance(parts, list) or not parts[0]:
        return None
    return "-".join(f"{int(part):02d}" for part in parts[0] if part)


def invert_abstract(index: Any) -> str | None:
    if not isinstance(index, dict):
        return None
    positions: list[tuple[int, str]] = []
    for word, slots in index.items():
        if isinstance(slots, list):
            positions.extend((int(slot), str(word)) for slot in slots)
    if not positions:
        return None
    return " ".join(word for _, word in sorted(positions))


def add_text(parent: ET.Element, tag: str, value: Any, **attrs: str) -> ET.Element | None:
    text = text_or_none(value)
    if not text:
        return None
    child = ET.SubElement(parent, f"{{{MODS_NS}}}{tag}", attrs)
    child.text = text
    return child


def add_title(root: ET.Element, title: str | None, subtitle: str | None = None) -> None:
    if not title:
        return
    title_info = ET.SubElement(root, f"{{{MODS_NS}}}titleInfo")
    add_text(title_info, "title", title)
    add_text(title_info, "subTitle", subtitle)


def add_name(root: ET.Element, name: str, role: str = "author") -> None:
    name_el = ET.SubElement(root, f"{{{MODS_NS}}}name", {"type": "personal"})
    add_text(name_el, "namePart", name)
    role_el = ET.SubElement(name_el, f"{{{MODS_NS}}}role")
    add_text(role_el, "roleTerm", role, type="text")


def add_origin(root: ET.Element, record: dict[str, Any], crossref: dict[str, Any], openalex: dict[str, Any]) -> None:
    origin = ET.SubElement(root, f"{{{MODS_NS}}}originInfo")
    add_text(origin, "publisher", first_text(crossref.get("publisher")))

    date_issued = first_text(
        openalex.get("publication_date"),
        date_from_parts(crossref.get("published-print")),
        date_from_parts(crossref.get("published-online")),
        date_from_parts(crossref.get("published")),
        record.get("publication_year"),
    )
    if date_issued:
        attrs = {"encoding": "w3cdtf"} if re.match(r"^\d{4}(-\d{2}){0,2}$", date_issued) else {}
        add_text(origin, "dateIssued", date_issued, **attrs)


def crossref_names(crossref: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in crossref.get("author") or []:
        if not isinstance(item, dict):
            continue
        given = text_or_none(item.get("given"))
        family = text_or_none(item.get("family"))
        name = " ".join(part for part in [given, family] if part)
        if name:
            names.append(name)
    return names


def openalex_names(openalex: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in openalex.get("authorships") or []:
        if not isinstance(item, dict):
            continue
        author = item.get("author") or {}
        name = text_or_none(author.get("display_name"))
        if name:
            names.append(name)
    return names


def list_field(record: dict[str, Any], key: str) -> list[str]:
    value = record.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def add_identifiers(root: ET.Element, doi: str, record: dict[str, Any], crossref: dict[str, Any], openalex: dict[str, Any]) -> None:
    if doi:
        add_text(root, "identifier", doi, type="doi")

    openalex_id = first_text(openalex.get("id"), record.get("openalex_id"))
    if openalex_id:
        add_text(root, "identifier", openalex_id, type="openalex")

    for key, id_type in [("ISSN", "issn"), ("ISBN", "isbn")]:
        values = crossref.get(key) or crossref.get(key.lower()) or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            add_text(root, "identifier", value, type=id_type)


def add_related_host(root: ET.Element, record: dict[str, Any], crossref: dict[str, Any], openalex: dict[str, Any]) -> None:
    primary_location = openalex.get("primary_location") or {}
    primary_source = primary_location.get("source") or {}
    source_name = first_text(
        record.get("source_name"),
        primary_source.get("display_name"),
        (crossref.get("container-title") or [None])[0],
    )
    if not source_name:
        return

    related = ET.SubElement(root, f"{{{MODS_NS}}}relatedItem", {"type": "host"})
    title_info = ET.SubElement(related, f"{{{MODS_NS}}}titleInfo")
    add_text(title_info, "title", source_name)

    part = ET.SubElement(related, f"{{{MODS_NS}}}part")
    biblio = openalex.get("biblio") or {}
    volume = first_text(crossref.get("volume"), biblio.get("volume"))
    issue = first_text(crossref.get("issue"), biblio.get("issue"))
    first_page = first_text(crossref.get("page"), biblio.get("first_page"))
    last_page = first_text(biblio.get("last_page"))

    if volume:
        detail = ET.SubElement(part, f"{{{MODS_NS}}}detail", {"type": "volume"})
        add_text(detail, "number", volume)
    if issue:
        detail = ET.SubElement(part, f"{{{MODS_NS}}}detail", {"type": "issue"})
        add_text(detail, "number", issue)
    if first_page:
        extent = ET.SubElement(part, f"{{{MODS_NS}}}extent", {"unit": "pages"})
        if "-" in first_page:
            start, end = first_page.split("-", 1)
            add_text(extent, "start", start)
            add_text(extent, "end", end)
        else:
            add_text(extent, "start", first_page)
            add_text(extent, "end", last_page)


def add_urls(root: ET.Element, record: dict[str, Any], openalex: dict[str, Any]) -> None:
    location = ET.SubElement(root, f"{{{MODS_NS}}}location")
    primary_location = openalex.get("primary_location") or {}
    best_oa_location = openalex.get("best_oa_location") or {}
    urls = [
        record.get("landing_page_url"),
        record.get("oa_url"),
        record.get("pdf_url"),
        primary_location.get("landing_page_url"),
        best_oa_location.get("pdf_url"),
    ]
    seen: set[str] = set()
    for url in urls:
        text = text_or_none(url)
        if text and text not in seen:
            add_text(location, "url", text)
            seen.add(text)
    if not seen:
        root.remove(location)


def add_subjects(root: ET.Element, record: dict[str, Any], openalex: dict[str, Any]) -> None:
    subjects = list_field(record, "concepts")
    subjects.extend(
        concept.get("display_name")
        for concept in openalex.get("concepts") or []
        if isinstance(concept, dict) and concept.get("display_name")
    )
    subjects.extend(
        keyword.get("display_name")
        for keyword in openalex.get("keywords") or []
        if isinstance(keyword, dict) and keyword.get("display_name")
    )

    seen: set[str] = set()
    for subject_text in subjects:
        subject_text = str(subject_text).strip()
        if not subject_text or subject_text.lower() in seen:
            continue
        seen.add(subject_text.lower())
        subject = ET.SubElement(root, f"{{{MODS_NS}}}subject")
        add_text(subject, "topic", subject_text)


def build_mods(
    record: dict[str, Any],
    *,
    crossref: dict[str, Any] | None,
    openalex: dict[str, Any] | None,
) -> ET.ElementTree:
    crossref = crossref or {}
    openalex = openalex or {}
    doi = normalize_doi(first_text(crossref.get("DOI"), openalex.get("doi"), record.get("doi")))

    root = ET.Element(
        f"{{{MODS_NS}}}mods",
        {
            "version": "3.7",
            f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOCATION,
        },
    )

    title = first_text(
        (crossref.get("title") or [None])[0],
        openalex.get("title"),
        record.get("title"),
    )
    subtitle = (crossref.get("subtitle") or [None])[0] if isinstance(crossref.get("subtitle"), list) else None
    add_title(root, title, subtitle)

    authors = crossref_names(crossref) or openalex_names(openalex) or list_field(record, "authors")
    for author in authors:
        add_name(root, author)

    add_origin(root, record, crossref, openalex)
    add_text(root, "genre", first_text(crossref.get("type"), openalex.get("type"), record.get("work_type")))
    add_identifiers(root, doi, record, crossref, openalex)
    add_related_host(root, record, crossref, openalex)

    abstract = first_text(record.get("abstract"), crossref.get("abstract"), invert_abstract(openalex.get("abstract_inverted_index")))
    add_text(root, "abstract", strip_xmlish_tags(abstract))
    add_subjects(root, record, openalex)
    add_urls(root, record, openalex)

    return ET.ElementTree(root)


def strip_xmlish_tags(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"<[^>]+>", "", value).strip()


def safe_stem(index: int, record: dict[str, Any]) -> str:
    title = text_or_none(record.get("title")) or "untitled"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", title)
    stem = re.sub(r"_+", "_", stem).strip("._-")
    return f"{index:03d}_{stem[:90] or 'untitled'}"


def write_xml(tree: ET.ElementTree, path: Path) -> None:
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = load_records(input_path)
    if args.limit:
        records = records[: args.limit]

    contact = f" ({args.email})" if args.email else ""
    user_agent = f"lit-skill-mods-fetcher/1.0{contact}"

    manifest: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        doi = normalize_doi(record.get("doi"))
        output_path = out_dir / f"{safe_stem(index, record)}.mods.xml"
        if output_path.exists() and not args.force:
            manifest.append(
                {
                    "index": index,
                    "title": record.get("title"),
                    "doi": doi,
                    "openalex_id": record.get("openalex_id"),
                    "mods_xml": str(output_path),
                    "status": "skipped_existing",
                }
            )
            continue

        crossref_result = fetch_crossref(doi, timeout=args.timeout, retries=args.retries, user_agent=user_agent)
        time.sleep(args.sleep)
        openalex_result = fetch_openalex(
            openalex_work_url(record, doi),
            timeout=args.timeout,
            retries=args.retries,
            user_agent=user_agent,
            email=args.email,
        )
        time.sleep(args.sleep)

        if not crossref_result.ok and not openalex_result.ok:
            status = "failed"
            error = "; ".join(
                item
                for item in [
                    f"crossref={crossref_result.status}:{crossref_result.error or ''}",
                    f"openalex={openalex_result.status}:{openalex_result.error or ''}",
                ]
                if item
            )
        else:
            tree = build_mods(
                record,
                crossref=crossref_result.data if crossref_result.ok else None,
                openalex=openalex_result.data if openalex_result.ok else None,
            )
            write_xml(tree, output_path)
            status = "ok"
            error = None

        manifest_row = {
            "index": index,
            "title": record.get("title"),
            "doi": doi,
            "openalex_id": record.get("openalex_id"),
            "mods_xml": str(output_path) if status == "ok" else "",
            "status": status,
            "crossref_status": crossref_result.status,
            "openalex_status": openalex_result.status,
            "error": error or "",
        }
        manifest.append(manifest_row)
        print(f"[{index:03d}/{len(records):03d}] {status}: {record.get('title')}", flush=True)

    manifest_json = out_dir / "manifest.json"
    manifest_csv = out_dir / "manifest.csv"
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()) if manifest else ["status"])
        writer.writeheader()
        writer.writerows(manifest)

    ok_count = sum(1 for row in manifest if row["status"] in {"ok", "skipped_existing"})
    failed_count = sum(1 for row in manifest if row["status"] == "failed")
    print(f"Done: {ok_count} available, {failed_count} failed. Manifest: {manifest_json}")
    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
