#!/usr/bin/env python3
"""Extract images and likely figure/table captions from a PDF for review drafting.

Extracted images are reading aids. For final literature reviews, prefer
redrawn/original figures with source attribution instead of copying paper
figures verbatim.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


CAPTION_RE = re.compile(
    r"(?im)^\s*((?:fig(?:ure)?|图|table|表)\s*\.?\s*[\w\-\.一二三四五六七八九十]+[:：.\s].{0,400})"
)


@dataclass
class ExtractedImage:
    page: int
    index: int
    path: str
    width: int | None = None
    height: int | None = None


@dataclass
class CaptionHit:
    page: int
    text: str


def _safe_stem(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("_") or "paper"


def extract_pdf(input_pdf: Path, output_dir: Path, render_pages: bool, page_scale: float) -> dict:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise SystemExit(
            "PyMuPDF is required. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    input_pdf = input_pdf.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    figures_dir = output_dir / "figures"
    pages_dir = output_dir / "pages"
    figures_dir.mkdir(parents=True, exist_ok=True)
    if render_pages:
        pages_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(input_pdf)
    stem = _safe_stem(input_pdf)
    images: list[ExtractedImage] = []
    captions: list[CaptionHit] = []
    page_renders: list[str] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_no = page_idx + 1

        text = page.get_text("text") or ""
        for match in CAPTION_RE.finditer(text):
            caption = " ".join(match.group(1).split())
            captions.append(CaptionHit(page=page_no, text=caption))

        for img_idx, img in enumerate(page.get_images(full=True), start=1):
            xref = img[0]
            info = doc.extract_image(xref)
            ext = info.get("ext", "png")
            out = figures_dir / f"{stem}_p{page_no:03d}_img{img_idx:02d}.{ext}"
            out.write_bytes(info["image"])
            images.append(
                ExtractedImage(
                    page=page_no,
                    index=img_idx,
                    path=str(out.relative_to(output_dir)),
                    width=info.get("width"),
                    height=info.get("height"),
                )
            )

        if render_pages:
            pix = page.get_pixmap(matrix=fitz.Matrix(page_scale, page_scale), alpha=False)
            out = pages_dir / f"{stem}_p{page_no:03d}.png"
            pix.save(out)
            page_renders.append(str(out.relative_to(output_dir)))

    captions_md = output_dir / "captions.md"
    with captions_md.open("w", encoding="utf-8") as f:
        f.write(f"# Captions extracted from {input_pdf.name}\n\n")
        if not captions:
            f.write("No likely figure/table captions found.\n")
        for hit in captions:
            f.write(f"- Page {hit.page}: {hit.text}\n")

    manifest = {
        "input": str(input_pdf),
        "pages": len(doc),
        "images": [asdict(x) for x in images],
        "captions": [asdict(x) for x in captions],
        "page_renders": page_renders,
        "notes": [
            "Use extracted images as reading aids.",
            "For final reviews, prefer redrawn/original figures with proper attribution.",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract images and likely captions from a PDF.")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Input PDF path.")
    parser.add_argument("--output-dir", "-o", type=Path, required=True, help="Output directory.")
    parser.add_argument("--render-pages", action="store_true", help="Also render full PDF pages as PNG.")
    parser.add_argument("--page-scale", type=float, default=2.0, help="Scale factor for page rendering.")
    args = parser.parse_args()

    manifest = extract_pdf(args.input, args.output_dir, args.render_pages, args.page_scale)
    out_dir = Path(args.output_dir).expanduser().resolve()
    print(f"OUTPUT_DIR={out_dir}")
    print(f"IMAGES={len(manifest['images'])}")
    print(f"CAPTIONS={len(manifest['captions'])}")
    print(f"MANIFEST={out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
