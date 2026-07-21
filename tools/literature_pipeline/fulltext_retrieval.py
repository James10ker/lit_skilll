from __future__ import annotations

import mimetypes
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .normalization import normalize_arxiv_id
from .schema import Paper


OPEN_HOSTS = {
    "arxiv.org", "export.arxiv.org", "pmc.ncbi.nlm.nih.gov", "aclanthology.org",
    "openreview.net", "hal.science", "inria.hal.science",
}


@dataclass
class FulltextCandidate:
    url: str
    format: str
    source: str
    priority: int


def discover_candidates(paper: Paper) -> list[FulltextCandidate]:
    candidates: list[FulltextCandidate] = []
    arxiv_id = normalize_arxiv_id(paper.arxiv_id)
    if arxiv_id:
        candidates.extend([
            FulltextCandidate(f"https://export.arxiv.org/api/query?id_list={arxiv_id}", "atom", "arxiv", 20),
            FulltextCandidate(f"https://arxiv.org/pdf/{arxiv_id}.pdf", "pdf", "arxiv", 50),
        ])
    for version in paper.versions:
        url = str(version.get("url") or "").strip()
        if url:
            candidates.extend(_candidate_from_url(url))
    if paper.url:
        candidates.extend(_candidate_from_url(paper.url))
    unique: dict[str, FulltextCandidate] = {}
    for candidate in candidates:
        if candidate.url not in unique or candidate.priority < unique[candidate.url].priority:
            unique[candidate.url] = candidate
    return sorted(unique.values(), key=lambda item: item.priority)


def _candidate_from_url(url: str) -> list[FulltextCandidate]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.casefold().removeprefix("www.")
    suffix = Path(parsed.path).suffix.casefold()
    if host not in OPEN_HOSTS and suffix != ".pdf":
        return []
    if "pmc.ncbi.nlm.nih.gov" in host:
        base = url.rstrip("/")
        return [FulltextCandidate(base + "/?report=xml", "jats_xml", "pubmed_central", 10), FulltextCandidate(url, "html", "pubmed_central", 20)]
    if suffix == ".pdf" or "/pdf" in parsed.path:
        return [FulltextCandidate(url, "pdf", host, 50)]
    return [FulltextCandidate(url, "html", host, 30)]


def download_candidate(candidate: FulltextCandidate, destination: Path, *, timeout: int = 45) -> tuple[Path | None, str]:
    """Download only an explicitly discovered open candidate; never follows auth workarounds."""
    parsed = urllib.parse.urlparse(candidate.url)
    host = parsed.netloc.casefold().removeprefix("www.")
    if host not in OPEN_HOSTS and Path(parsed.path).suffix.casefold() != ".pdf":
        return None, "URL is not an approved open repository or direct PDF."
    request = urllib.request.Request(candidate.url, headers={"User-Agent": "literature-review-skill/1.0", "Accept": "application/xml,text/html,application/pdf;q=0.9,*/*;q=0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if response.status in {401, 403, 407, 429}:
                return None, f"Access refused with HTTP {response.status}; no bypass attempted."
            data = response.read()
    except Exception as exc:  # the failure is returned and must be persisted by the caller
        return None, f"Fetch failed: {type(exc).__name__}: {exc}"
    guessed = mimetypes.guess_extension(content_type) or ""
    suffix = {"jats_xml": ".xml", "html": ".html", "pdf": ".pdf", "atom": ".xml"}.get(candidate.format, guessed or ".bin")
    path = destination.with_suffix(suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if len(data) < 256:
        return None, "Downloaded response was too small to be a paper document."
    if candidate.format == "pdf" and not data.startswith(b"%PDF"):
        return None, "Expected a PDF but the response was not a PDF."
    return path, ""
