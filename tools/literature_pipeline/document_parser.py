from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .schema import DocumentBlock, FulltextDocument


SECTION_HINTS = {
    "introduction", "background", "method", "methods", "methodology", "materials and methods",
    "experiment", "experiments", "results", "discussion", "limitations", "limitation",
    "conclusion", "conclusions", "future work",
}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _xml_text(node: ET.Element) -> str:
    return _clean(" ".join(node.itertext()))


def parse_jats(path: Path, *, paper_id: str, source_url: str = "") -> FulltextDocument:
    root = ET.parse(path).getroot()
    blocks: list[DocumentBlock] = []
    sections: list[dict[str, object]] = []
    paragraph_index = 0
    for sec_index, section in enumerate(root.findall(".//sec"), start=1):
        title_node = section.find("./title")
        title = _xml_text(title_node) if title_node is not None else f"Section {sec_index}"
        section_block_ids: list[str] = []
        for paragraph in section.findall("./p"):
            text = _xml_text(paragraph)
            if not text:
                continue
            paragraph_index += 1
            block_id = f"p-{paragraph_index}"
            blocks.append(DocumentBlock(block_id=block_id, kind="paragraph", text=text, section=title, paragraph=paragraph_index))
            section_block_ids.append(block_id)
        sections.append({"title": title, "block_ids": section_block_ids})
    for table_index, table in enumerate(root.findall(".//table-wrap"), start=1):
        label = _xml_text(table.find("./label")) if table.find("./label") is not None else f"Table {table_index}"
        caption = _xml_text(table.find("./caption")) if table.find("./caption") is not None else ""
        blocks.append(DocumentBlock(block_id=f"table-{table_index}", kind="table", text=_xml_text(table), table_id=label, caption=caption))
    complete = bool(blocks) and bool(root.findall(".//body"))
    return FulltextDocument(paper_id, source_url or str(path), "jats_xml", "stdlib-etree", "fulltext" if complete else "section_level", sections, blocks, [], complete)


class _HTMLExtractor(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_tag = ""
        self.current: list[str] = []
        self.blocks: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "p", "figcaption", "caption"}:
            self.current_tag = tag
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.current_tag:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self.current_tag:
            text = _clean(" ".join(self.current))
            if text:
                self.blocks.append((tag, text))
            self.current_tag = ""
            self.current = []


def parse_html(path: Path, *, paper_id: str, source_url: str = "") -> FulltextDocument:
    parser = _HTMLExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    blocks: list[DocumentBlock] = []
    sections: list[dict[str, object]] = []
    current_section = ""
    paragraph_index = 0
    for tag, text in parser.blocks:
        if tag.startswith("h"):
            current_section = text
            sections.append({"title": text, "block_ids": []})
            continue
        paragraph_index += 1
        kind = "caption" if tag in {"caption", "figcaption"} else "paragraph"
        block_id = f"p-{paragraph_index}"
        blocks.append(DocumentBlock(block_id, kind, text, current_section, paragraph=paragraph_index))
        if sections:
            sections[-1]["block_ids"].append(block_id)
    named = {str(item["title"]).casefold() for item in sections}
    relevant = any(any(hint in title for hint in SECTION_HINTS) for title in named)
    access = "fulltext" if relevant and len(blocks) >= 10 else "section_level" if blocks else "abstract_only"
    return FulltextDocument(paper_id, source_url or str(path), "html", "stdlib-htmlparser", access, sections, blocks, [], access == "fulltext")


def parse_pdf(path: Path, *, paper_id: str, source_url: str = "") -> FulltextDocument:
    try:
        import fitz  # type: ignore
    except ImportError:
        return FulltextDocument(paper_id, source_url or str(path), "pdf", "unavailable", "metadata_only", [], [], ["PyMuPDF is not installed; PDF was not parsed."], False)
    document = fitz.open(path)
    blocks: list[DocumentBlock] = []
    for page_index, page in enumerate(document, start=1):
        for block_index, raw in enumerate(page.get_text("blocks"), start=1):
            text = _clean(str(raw[4]))
            if text:
                blocks.append(DocumentBlock(f"page-{page_index}-block-{block_index}", "paragraph", text, page=page_index))
    access = "fulltext" if len(blocks) >= 20 else "section_level" if blocks else "metadata_only"
    warnings = [] if blocks else ["PDF contained no extractable text; OCR is not performed in the first version."]
    return FulltextDocument(paper_id, source_url or str(path), "pdf", "pymupdf", access, [], blocks, warnings, access == "fulltext")


def parse_document(path: Path, *, paper_id: str, source_url: str = "", format_hint: str = "") -> FulltextDocument:
    kind = (format_hint or path.suffix.lstrip(".")).casefold()
    if kind in {"xml", "jats", "jats_xml", "nxml"}:
        return parse_jats(path, paper_id=paper_id, source_url=source_url)
    if kind in {"html", "htm"}:
        return parse_html(path, paper_id=paper_id, source_url=source_url)
    if kind == "pdf":
        return parse_pdf(path, paper_id=paper_id, source_url=source_url)
    return FulltextDocument(paper_id, source_url or str(path), kind or "unknown", "none", "metadata_only", [], [], [f"Unsupported document format: {kind or '<missing>'}"], False)
