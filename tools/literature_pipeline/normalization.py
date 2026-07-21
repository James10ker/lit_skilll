from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote


def normalize_doi(value: str | None) -> str:
    text = unquote(str(value or "")).strip().lower()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text)
    return text.rstrip(" .") if text.startswith("10.") else ""


def normalize_arxiv_id(value: str | None) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:)", "", text)
    text = re.sub(r"\.pdf$", "", text)
    text = re.sub(r"v\d+$", "", text)
    return text if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})", text) else ""


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_author(value: str | None) -> str:
    text = normalize_title(value)
    parts = text.split()
    return " ".join(parts[-2:]) if len(parts) >= 2 else text
