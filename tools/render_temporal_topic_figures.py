#!/usr/bin/env python3
"""Render annual publication counts and two-window topic word clouds.

The renderer uses only the Python standard library. It emits SVG directly and,
when rsvg-convert is available, matching PNG files suitable for LaTeX.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


BAR_COLOR = "#b2221b"
TREND_COLOR = "#9a6a19"
TOPIC_COLORS = ("#66d7e8", "#9ee6c6", "#8da9ff", "#f4c66a", "#b48cff", "#ffaf72", "#ff88ae")
PLACEHOLDERS = {"", "-", "--", "n/a", "na", "none", "null", "unknown", "unknown topic"}


@dataclass(frozen=True)
class Record:
    title: str
    year: int
    topics: tuple[str, ...]


@dataclass(frozen=True)
class WordBox:
    text: str
    count: int
    x: float
    y: float
    width: float
    height: float
    font_size: float
    color: str


def split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        text = str(value).strip()
        if not text:
            return []
        delimiter = next((item for item in (";", "|", "\n") if item in text), ";")
        raw = text.split(delimiter)
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        label = str(item).strip()
        normalized = label.lower()
        if normalized not in PLACEHOLDERS and normalized not in seen:
            seen.add(normalized)
            values.append(label)
    return values


def parse_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        year = int(float(str(value).strip()))
    except ValueError:
        return None
    return year if 1000 <= year <= 3000 else None


def normalize_record(raw: dict[str, Any], index: int) -> Record | None:
    year = parse_year(raw.get("year") or raw.get("publication_year"))
    if year is None:
        return None
    topic_value = next(
        (
            raw.get(key)
            for key in ("topics", "keywords", "theme", "concepts", "matched_queries")
            if raw.get(key)
        ),
        None,
    )
    topics = tuple(split_values(topic_value))
    title = str(raw.get("title") or raw.get("paper_title") or f"record-{index + 1}").strip()
    return Record(title=title, year=year, topics=topics)


def load_records(path: Path) -> tuple[list[Record], list[str]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            raw_records: Any = list(csv.DictReader(handle))
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_records = data.get("records", data) if isinstance(data, dict) else data
    if not isinstance(raw_records, list):
        raise ValueError("input must be a JSON list, a JSON object with records, or a CSV file")

    records: list[Record] = []
    warnings: list[str] = []
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            warnings.append(f"record {index + 1}: expected an object")
            continue
        record = normalize_record(raw, index)
        if record is None:
            warnings.append(f"record {index + 1}: missing or invalid publication year")
            continue
        if not record.topics:
            warnings.append(f"{record.title}: missing topics/keywords/concepts")
        records.append(record)
    if not records:
        raise ValueError("no records with valid publication years found")
    return records, warnings


def annual_counts(records: list[Record], start_year: int, end_year: int) -> dict[int, int]:
    observed = Counter(record.year for record in records if start_year <= record.year <= end_year)
    return {year: observed.get(year, 0) for year in range(start_year, end_year + 1)}


def solve_3x3(matrix: list[list[float]], vector: list[float]) -> tuple[float, float, float]:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        if abs(divisor) < 1e-12:
            return 0.0, 0.0, sum(vector) / max(1.0, matrix[0][0])
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return augmented[0][3], augmented[1][3], augmented[2][3]


def quadratic_fit(counts: dict[int, int]) -> tuple[float, float, float, float]:
    years = list(counts)
    values = [float(counts[year]) for year in years]
    center = sum(years) / len(years)
    xs = [year - center for year in years]
    sums = [sum(x**power for x in xs) for power in range(5)]
    matrix = [
        [sums[4], sums[3], sums[2]],
        [sums[3], sums[2], sums[1]],
        [sums[2], sums[1], sums[0]],
    ]
    vector = [
        sum((x**2) * y for x, y in zip(xs, values)),
        sum(x * y for x, y in zip(xs, values)),
        sum(values),
    ]
    a, b_centered, c_centered = solve_3x3(matrix, vector)
    b = b_centered - 2 * a * center
    c = a * center**2 - b_centered * center + c_centered
    predicted = [a * year**2 + b * year + c for year in years]
    mean = sum(values) / len(values)
    total = sum((value - mean) ** 2 for value in values)
    residual = sum((value - fit) ** 2 for value, fit in zip(values, predicted))
    r_squared = 1.0 - residual / total if total > 0 else 1.0
    return a, b, c, r_squared


def nice_ceiling(value: int) -> int:
    if value <= 5:
        return 5
    magnitude = 10 ** max(0, int(math.floor(math.log10(value))) - 1)
    return int(math.ceil(value / magnitude) * magnitude)


def render_annual_svg(counts: dict[int, int], title: str, width: int = 1600, height: int = 900) -> str:
    left, right, top, bottom = 108.0, 48.0, 95.0, 142.0
    chart_w, chart_h = width - left - right, height - top - bottom
    max_y = nice_ceiling(max(counts.values(), default=0))
    years = list(counts)
    slot = chart_w / max(1, len(years))
    bar_w = min(42.0, slot * 0.48)
    a, b, c, r_squared = quadratic_fit(counts)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2:.1f}" y="42" text-anchor="middle" font-family="Times New Roman, Georgia, serif" font-size="28" font-weight="700" font-style="italic">{escape(title)}</text>',
    ]
    tick_step = max(1, max_y // 10)
    for value in range(0, max_y + 1, tick_step):
        y = top + chart_h - value / max_y * chart_h
        parts.append(f'<line x1="{left - 8}" y1="{y:.2f}" x2="{left}" y2="{y:.2f}" stroke="#111"/>')
        parts.append(f'<text x="{left - 16}" y="{y + 6:.2f}" text-anchor="end" font-family="Times New Roman, Georgia, serif" font-size="18">{value}</text>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#111" stroke-width="1.5"/>')
    parts.append(f'<line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#111" stroke-width="1.5"/>')

    for index, year in enumerate(years):
        center_x = left + (index + 0.5) * slot
        bar_h = counts[year] / max_y * chart_h
        y = top + chart_h - bar_h
        parts.append(f'<rect x="{center_x - bar_w / 2:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{bar_h:.2f}" fill="{BAR_COLOR}"/>')
        parts.append(
            f'<text x="{center_x + 3:.2f}" y="{top + chart_h + 30:.2f}" transform="rotate(-40 {center_x + 3:.2f} {top + chart_h + 30:.2f})" text-anchor="end" font-family="Times New Roman, Georgia, serif" font-size="18" font-weight="700">{year}</text>'
        )

    points: list[str] = []
    samples = max(60, len(years) * 10)
    first_year, last_year = years[0], years[-1]
    for index in range(samples + 1):
        year = first_year + (last_year - first_year) * index / samples
        value = max(0.0, min(max_y, a * year**2 + b * year + c))
        x = left + ((year - first_year) / max(1, last_year - first_year) * (len(years) - 1) + 0.5) * slot
        y = top + chart_h - value / max_y * chart_h
        points.append(f"{x:.2f},{y:.2f}")
    parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{TREND_COLOR}" stroke-width="3"/>')

    legend_x, legend_y = left + 100, top + 120
    parts.append(f'<rect x="{legend_x}" y="{legend_y}" width="30" height="18" fill="{BAR_COLOR}"/>')
    parts.append(f'<text x="{legend_x + 38}" y="{legend_y + 16}" font-family="Times New Roman, Georgia, serif" font-size="21" font-weight="700">Publication count</text>')
    parts.append(f'<line x1="{legend_x}" y1="{legend_y + 42}" x2="{legend_x + 30}" y2="{legend_y + 42}" stroke="{TREND_COLOR}" stroke-width="3"/>')
    parts.append(f'<text x="{legend_x + 38}" y="{legend_y + 49}" font-family="Times New Roman, Georgia, serif" font-size="21" font-weight="700">Polynomial trend</text>')
    equation = f"y = {a:.4g}x^2 {b:+.4g}x {c:+.4g}; R^2 = {r_squared:.4f}"
    parts.append(f'<text x="{left + chart_w * 0.48:.2f}" y="{top + chart_h * 0.28:.2f}" font-family="Times New Roman, Georgia, serif" font-size="19" font-weight="700">{escape(equation)}</text>')
    parts.append(f'<text x="{width / 2:.2f}" y="{height - 18}" text-anchor="middle" font-family="Times New Roman, Georgia, serif" font-size="23" font-weight="700">Year</text>')
    parts.append(f'<text x="28" y="{top + chart_h / 2:.2f}" transform="rotate(-90 28 {top + chart_h / 2:.2f})" text-anchor="middle" font-family="Times New Roman, Georgia, serif" font-size="23" font-weight="700">Publication count</text>')
    parts.append("</svg>\n")
    return "".join(parts)


def estimate_text_width(text: str, font_size: float) -> float:
    units = sum(0.95 if ord(char) > 127 else 0.34 if char == " " else 0.56 for char in text)
    return max(font_size * 1.5, units * font_size)


def boxes_overlap(left: WordBox, right: WordBox, pad: float = 4.0) -> bool:
    return not (
        left.x + left.width / 2 + pad <= right.x - right.width / 2
        or right.x + right.width / 2 + pad <= left.x - left.width / 2
        or left.y + left.height / 2 + pad <= right.y - right.height / 2
        or right.y + right.height / 2 + pad <= left.y - left.height / 2
    )


def place_words(
    counts: Counter[str],
    *,
    panel_x: float,
    panel_y: float,
    panel_w: float,
    panel_h: float,
    max_topics: int,
) -> tuple[list[WordBox], list[str]]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:max_topics]
    if not ranked:
        return [], []
    low, high = ranked[-1][1], ranked[0][1]
    boxes: list[WordBox] = []
    skipped: list[str] = []
    center_x, center_y = panel_x + panel_w / 2, panel_y + panel_h / 2
    for rank, (text, count) in enumerate(ranked):
        ratio = 1.0 if high == low else (math.sqrt(count) - math.sqrt(low)) / (math.sqrt(high) - math.sqrt(low))
        preferred_font_size = 18.0 + ratio * 34.0
        display = text if len(text) <= 34 else text[:31].rstrip() + "..."
        placed: WordBox | None = None
        for scale_factor in (1.0, 0.9, 0.8, 0.7, 0.6):
            font_size = max(12.0, preferred_font_size * scale_factor)
            box_w = estimate_text_width(display, font_size)
            box_h = font_size * 1.16
            for step in range(900):
                angle = step * 0.51 + rank * 0.77
                radius = 1.3 * step
                x = center_x + math.cos(angle) * radius
                y = center_y + math.sin(angle) * radius * 0.78
                candidate = WordBox(display, count, x, y, box_w, box_h, font_size, TOPIC_COLORS[rank % len(TOPIC_COLORS)])
                if x - box_w / 2 < panel_x + 12 or x + box_w / 2 > panel_x + panel_w - 12:
                    continue
                if y - box_h / 2 < panel_y + 12 or y + box_h / 2 > panel_y + panel_h - 12:
                    continue
                if any(boxes_overlap(candidate, other) for other in boxes):
                    continue
                placed = candidate
                break
            if placed is not None:
                break
        if placed is None:
            font_size = 10.0
            box_w = estimate_text_width(display, font_size)
            box_h = font_size * 1.16
            y = panel_y + 18.0
            while y <= panel_y + panel_h - 18.0 and placed is None:
                x = panel_x + box_w / 2 + 12.0
                while x <= panel_x + panel_w - box_w / 2 - 12.0:
                    candidate = WordBox(display, count, x, y, box_w, box_h, font_size, TOPIC_COLORS[rank % len(TOPIC_COLORS)])
                    if not any(boxes_overlap(candidate, other) for other in boxes):
                        placed = candidate
                        break
                    x += 12.0
                y += 14.0
        if placed is None:
            skipped.append(text)
        else:
            boxes.append(placed)
    return boxes, skipped


def topic_counts(records: list[Record], start_year: int, end_year: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        if start_year <= record.year <= end_year:
            counts.update(record.topics)
    return counts


def render_wordcloud_svg(
    earlier_counts: Counter[str],
    recent_counts: Counter[str],
    *,
    earlier_window: tuple[int, int],
    recent_window: tuple[int, int],
    title: str,
    max_topics: int,
    width: int = 1600,
    height: int = 900,
) -> tuple[str, dict[str, Any]]:
    margin, gap, top, bottom = 42.0, 30.0, 166.0, 54.0
    panel_w = (width - 2 * margin - gap) / 2
    panel_h = height - top - bottom
    content_y = top + 98.0
    content_h = panel_h - 138.0
    earlier_boxes, earlier_skipped = place_words(
        earlier_counts, panel_x=margin + 20.0, panel_y=content_y, panel_w=panel_w - 40.0, panel_h=content_h, max_topics=max_topics
    )
    recent_x = margin + panel_w + gap
    recent_boxes, recent_skipped = place_words(
        recent_counts, panel_x=recent_x + 20.0, panel_y=content_y, panel_w=panel_w - 40.0, panel_h=content_h, max_topics=max_topics
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        '<linearGradient id="pageGradient" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#061426"/><stop offset="0.55" stop-color="#0b1c32"/><stop offset="1" stop-color="#171a38"/></linearGradient>',
        '<radialGradient id="earlyPanel" cx="15%" cy="10%" r="110%"><stop offset="0" stop-color="#173b52"/><stop offset="1" stop-color="#0a1d31"/></radialGradient>',
        '<radialGradient id="recentPanel" cx="85%" cy="10%" r="110%"><stop offset="0" stop-color="#2a2551"/><stop offset="1" stop-color="#0d1d31"/></radialGradient>',
        '</defs>',
        '<rect width="100%" height="100%" fill="url(#pageGradient)"/>',
        '<path d="M0 132 C340 48 610 196 940 104 S1350 68 1600 128" fill="none" stroke="#75a7c9" stroke-opacity="0.12"/>',
        '<text x="48" y="48" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" letter-spacing="4" fill="#6fd9e9">THEMATIC LANDSCAPE</text>',
        f'<text x="48" y="94" font-family="Arial, Helvetica, sans-serif" font-size="34" font-weight="700" fill="#f4f8fc">{escape(title)}</text>',
        '<text x="48" y="126" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#9db2c7">Two adjacent five-year windows · type size reflects within-window topic frequency</text>',
    ]
    for panel_index, (x, window, boxes, counts, gradient, accent) in enumerate((
        (margin, earlier_window, earlier_boxes, earlier_counts, "earlyPanel", "#61d6e6"),
        (recent_x, recent_window, recent_boxes, recent_counts, "recentPanel", "#b68cff"),
    )):
        parts.append(f'<rect x="{x:.2f}" y="{top:.2f}" width="{panel_w:.2f}" height="{panel_h:.2f}" rx="28" fill="url(#{gradient})" stroke="#46617b" stroke-opacity="0.62"/>')
        parts.append(f'<rect x="{x + 24:.2f}" y="{top + 28:.2f}" width="6" height="54" rx="3" fill="{accent}"/>')
        parts.append(f'<text x="{x + 46:.2f}" y="{top + 57:.2f}" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="700" fill="#f5f8fc">{window[0]}-{window[1]}</text>')
        parts.append(f'<text x="{x + 47:.2f}" y="{top + 81:.2f}" font-family="Arial, Helvetica, sans-serif" font-size="11" font-weight="700" letter-spacing="2" fill="#8da5bc">FIVE-YEAR TOPIC WINDOW</text>')
        parts.append(f'<text x="{x + panel_w - 28:.2f}" y="{top + 55:.2f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="25" font-weight="700" fill="#f5f8fc">{sum(counts.values())}</text>')
        parts.append(f'<text x="{x + panel_w - 28:.2f}" y="{top + 79:.2f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="10" font-weight="700" letter-spacing="1.5" fill="#8da5bc">TOPIC ASSIGNMENTS</text>')
        parts.append(f'<text x="{x + panel_w - 25:.2f}" y="{top + panel_h * 0.48:.2f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="164" font-weight="700" fill="#ffffff" opacity="0.03">{str(window[0])[2:]}–{str(window[1])[2:]}</text>')
        parts.append(f'<line x1="{x + 45:.2f}" y1="{top + 96:.2f}" x2="{x + panel_w - 28:.2f}" y2="{top + 96:.2f}" stroke="#89a7c2" stroke-opacity="0.28"/>')
        for box in boxes:
            parts.append(
                f'<text x="{box.x:.2f}" y="{box.y + box.font_size * 0.34:.2f}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="{box.font_size:.1f}" font-weight="700" fill="{box.color}">{escape(box.text)}</text>'
            )
        parts.append(f'<circle cx="{x + 48:.2f}" cy="{top + panel_h - 24:.2f}" r="3.5" fill="{accent}"/>')
        parts.append(f'<text x="{x + 62:.2f}" y="{top + panel_h - 19:.2f}" font-family="Arial, Helvetica, sans-serif" font-size="10" font-weight="700" letter-spacing="1" fill="#7f98b0">TYPE SIZE = WITHIN-WINDOW FREQUENCY</text>')
        parts.append(f'<text x="{x + panel_w - 28:.2f}" y="{top + panel_h - 19:.2f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="10" font-weight="700" letter-spacing="1" fill="#7f98b0">TOPIC LABELS ONLY</text>')
    parts.append("</svg>\n")
    checks = {
        "earlier_topic_labels": len(earlier_boxes),
        "recent_topic_labels": len(recent_boxes),
        "earlier_skipped": earlier_skipped,
        "recent_skipped": recent_skipped,
        "word_overlaps": [],
    }
    for boxes in (earlier_boxes, recent_boxes):
        for index, left in enumerate(boxes):
            for right in boxes[index + 1 :]:
                if boxes_overlap(left, right, pad=0.0):
                    checks["word_overlaps"].append(f"{left.text} overlaps {right.text}")
    return "".join(parts), checks


def run_pipeline(
    records: list[Record],
    *,
    start_year: int,
    end_year: int,
    window_years: int,
    max_topics: int,
    annual_title: str,
    topic_title: str,
    warnings: list[str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    if start_year > end_year:
        raise ValueError("start year must not exceed end year")
    if window_years < 1:
        raise ValueError("window years must be positive")
    recent_window = (end_year - window_years + 1, end_year)
    earlier_window = (end_year - 2 * window_years + 1, end_year - window_years)
    counts = annual_counts(records, start_year, end_year)
    earlier = topic_counts(records, *earlier_window)
    recent = topic_counts(records, *recent_window)
    annual_svg = render_annual_svg(counts, annual_title)
    wordcloud_svg, wordcloud_checks = render_wordcloud_svg(
        earlier,
        recent,
        earlier_window=earlier_window,
        recent_window=recent_window,
        title=topic_title,
        max_topics=max_topics,
    )
    earlier_records = sum(earlier_window[0] <= record.year <= earlier_window[1] for record in records)
    recent_records = sum(recent_window[0] <= record.year <= recent_window[1] for record in records)
    validation = {
        "has_annual_publications": sum(counts.values()) > 0,
        "earlier_window_has_records": earlier_records > 0,
        "recent_window_has_records": recent_records > 0,
        "earlier_window_has_topics": bool(earlier),
        "recent_window_has_topics": bool(recent),
        "wordcloud_overlap_free": not wordcloud_checks["word_overlaps"],
        "wordcloud_topic_coverage": (
            wordcloud_checks["earlier_topic_labels"] >= min(10, len(earlier), max_topics)
            and wordcloud_checks["recent_topic_labels"] >= min(10, len(recent), max_topics)
        ),
    }
    validation["passed"] = all(validation.values())
    report = {
        "input_records": len(records),
        "annual_range": {"start": start_year, "end": end_year},
        "annual_counts": counts,
        "quadratic_fit": dict(zip(("a", "b", "c", "r_squared"), quadratic_fit(counts))),
        "topic_windows": {
            "earlier": {
                "start": earlier_window[0],
                "end": earlier_window[1],
                "record_count": earlier_records,
                "topic_counts": dict(earlier.most_common()),
            },
            "recent": {
                "start": recent_window[0],
                "end": recent_window[1],
                "record_count": recent_records,
                "topic_counts": dict(recent.most_common()),
            },
        },
        "wordcloud_checks": wordcloud_checks,
        "warnings": (warnings or [])[:100],
        "validation": validation,
        "style_contract": {
            "annual_chart": "white background, dark-red bars, brown-gold polynomial trend, serif typography",
            "topic_wordcloud": "wide dark thematic landscape with two adjacent non-overlapping five-year panels and high-contrast hierarchy",
        },
    }
    return {"annual_publications": annual_svg, "topic_wordcloud": wordcloud_svg}, report


def write_outputs(figures: dict[str, str], output_dir: Path, prefix: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    converter = shutil.which("rsvg-convert")
    for name, svg in figures.items():
        svg_path = output_dir / f"{prefix}_{name}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        outputs[f"{name}_svg"] = str(svg_path.resolve())
        if converter:
            png_path = output_dir / f"{prefix}_{name}.png"
            subprocess.run([converter, "-o", str(png_path), str(svg_path)], check=True)
            outputs[f"{name}_png"] = str(png_path.resolve())
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Render annual publication and two-window topic figures.")
    parser.add_argument("--input", "-i", type=Path, required=True, help="JSON or CSV publication records")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/figures"))
    parser.add_argument("--prefix", default="review")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--window-years", type=int, default=5)
    parser.add_argument("--max-topics", type=int, default=28)
    parser.add_argument("--annual-title", default="Figure X. Year-by-year number of publications")
    parser.add_argument("--topic-title", default="Figure X. Research topics across two five-year periods")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    records, warnings = load_records(args.input)
    start_year = args.start_year if args.start_year is not None else min(record.year for record in records)
    end_year = args.end_year if args.end_year is not None else max(record.year for record in records)
    figures, report = run_pipeline(
        records,
        start_year=start_year,
        end_year=end_year,
        window_years=args.window_years,
        max_topics=args.max_topics,
        annual_title=args.annual_title,
        topic_title=args.topic_title,
        warnings=warnings,
    )
    if not args.validate_only:
        report["outputs"] = write_outputs(figures, args.output_dir, args.prefix)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["validation"]["passed"]:
        print("VALID=failed")
        return 1
    print("VALID=ok")
    for key, path in report.get("outputs", {}).items():
        print(f"{key.upper()}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
