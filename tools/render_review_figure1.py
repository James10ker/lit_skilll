#!/usr/bin/env python3
"""Render a review-style "Figure 1" workflow diagram from JSON input.

This version exposes a stable pipeline for model/tool invocation:

Graph IR
-> logical validation
-> first render
-> layout quality assessment
-> auto-relayout / extra constraints
-> second render
-> readability check
-> final output
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import struct
import subprocess
import tempfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import ImageFont


DEFAULT_SPEC: dict[str, Any] = {
    "title": "Figure 1. Data collection and analyses",
    "stage_labels": ["Identification", "Screening", "Included"],
    "left_caption": "Data collection and filtering",
    "right_caption": (
        "Data analysis: bibliometric indicators, social network analysis, "
        "structural topic model, Mann-Kendall test"
    ),
    "strategy_boxes": [
        {
            "text": (
                "Strategy one (database search):\n"
                "Web of Science, ERIC, and Scopus\n"
                "(N=29184)"
            )
        },
        {
            "text": (
                "Strategy two (additional search):\n"
                "publications in International Conference on Artificial "
                "Intelligence in Education (long papers) and International "
                "Journal of Artificial Intelligence in Education\n"
                "(N=1202)"
            )
        },
    ],
    "total_box": (
        "Total publications retrieved from database search and additional search\n"
        "(N=30386)"
    ),
    "duplicate_label": "Duplicated publication exclusion",
    "manual_box": "Publications included for manual screening and filtering\n(N=14958)",
    "excluded_box": (
        "10439 publications were excluded:\n"
        "1) not related to education;\n"
        "2) no use of AI;\n"
        "3) about AI courses;\n"
        "4) e-learning or intelligent systems without AI techniques;\n"
        "5) deep learning mention not about AI techniques, but about learning deeply;\n"
        "6) survey, review, or position papers without specific AI application in educational settings"
    ),
    "analysis_box": "Publications included for data analysis\n(N=4519)",
    "citation_box": "Collect the number of citations received by each publication in Google Scholar",
    "analysis_steps": [
        "Trend analysis of annual publications",
        "Identification of top sources, countries/regions, and institutions",
        "Visualization of the scientific collaboration",
        "Topic identification and interpretations, topic popularity and trend analyses",
    ],
    "connector_styles": {
        "strategy_one_to_total": "arrow",
        "strategy_two_to_total": "arrow",
        "total_to_manual": "arrow",
        "total_to_duplicate": "line",
        "manual_to_excluded": "line",
        "manual_to_analysis": "arrow",
        "analysis_to_citation": "line",
        "analysis_panel_arrow": "arrow",
    },
    "layout": {
        "font_size": 16,
        "title_font_size": 34,
        "caption_font_size": 22,
        "stage_font_size": 26,
        "box_rx": 1,
        "panel_rx": 4,
        "stage_pill_rx": 18,
        "canvas_width": 1820,
        "canvas_height": 1380,
        "max_relayout_passes": 1,
    },
}


BODY_TEXT_PAD_Y = 38
BOX_GAP_TOLERANCE = 8
CONNECTOR_COLOR = "#111111"
PANEL_PADDING_BALANCE_TOLERANCE = 32.0
ALIGNMENT_TOLERANCE = 4.0
GAP_VARIANCE_TOLERANCE = 6.0
SIZE_VARIANCE_TOLERANCE = 6.0
MAX_EDGE_CROSSINGS = 0
MAX_TEXT_LINE_UNITS = 34.0
MIN_TEXT_PIXEL_HEIGHT = 12.0
MIN_INTER_PANEL_GAP = 48.0
MAX_INTER_PANEL_GAP = 100.0
MAX_INTER_PANEL_GAP_RATIO = 0.12
BIG_ARROW_TAIL_INSET = 15.0
BIG_ARROW_TIP_INSET = 15.0
MIN_BIG_ARROW_LENGTH = 48.0
PREFERRED_BIG_ARROW_LENGTH = 64.0
MAX_BIG_ARROW_LENGTH = 96.0
MIN_CONTENT_WIDTH_RATIO = 0.78
MAX_CONTENT_WIDTH_RATIO = 0.92
MIN_LEFT_PANEL_SHARE = 0.60
MAX_LEFT_PANEL_SHARE = 0.68
MIN_RIGHT_PANEL_SHARE = 0.22
MAX_RIGHT_PANEL_SHARE = 0.30
MIN_GAP_SHARE = 0.04
MAX_GAP_SHARE = 0.08
STAGE_PILLS = {
    "identification": (92.0, 275.0, 42.0, 170.0),
    "screening": (92.0, 605.0, 42.0, 150.0),
    "included": (92.0, 955.0, 42.0, 145.0),
}
BOX_SAFE_GAP = 18.0

BOX_STYLE_BY_ID = {
    "strategy_one": ("#eef5ff", "#4c7dd9"),
    "strategy_two": ("#eef5ff", "#4c7dd9"),
    "total_box": ("#eef5ff", "#4c7dd9"),
    "manual_box": ("#edf9f3", "#49a977"),
    "analysis_box": ("#edf9f3", "#49a977"),
    "duplicate_label": ("#fff6ea", "#d9963c"),
    "citation_box": ("#fff6ea", "#d9963c"),
    "excluded_box": ("#f4efff", "#8a68d6"),
    "analysis_step_1": ("#eef5ff", "#4c7dd9"),
    "analysis_step_2": ("#edf9f3", "#49a977"),
    "analysis_step_3": ("#fff6ea", "#d9963c"),
    "analysis_step_4": ("#f4efff", "#8a68d6"),
}

BOX_ICON_BY_ID = {
    "strategy_one": "source",
    "strategy_two": "source",
    "total_box": "merge",
    "manual_box": "filter",
    "analysis_box": "check",
    "duplicate_label": "exclude",
    "excluded_box": "exclude",
    "citation_box": "cite",
    "analysis_step_1": "trend",
    "analysis_step_2": "source",
    "analysis_step_3": "network",
    "analysis_step_4": "topic",
}


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    text: str
    font_size: int = 18
    rx: float = 24
    fill: str = "#f9fbff"
    stroke: str = "#4a78d0"
    stroke_width: float = 2.3
    id: str = ""


@dataclass
class NodeSpec:
    id: str
    text: str
    kind: str


@dataclass
class EdgeSpec:
    id: str
    source: str
    target: str
    style_key: str
    semantic: str


@dataclass
class DiagramIR:
    title: str
    stage_labels: list[str]
    left_caption: str
    right_caption: str
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
    analysis_steps: list[str]
    connector_styles: dict[str, str]
    layout: dict[str, Any]


@dataclass
class LayoutResult:
    width: int
    height: int
    left_panel: tuple[float, float, float, float]
    right_panel: tuple[float, float, float, float]
    boxes: dict[str, Box]
    analysis_order: list[str]
    large_arrow_y: float
    left_caption_y: float
    right_caption_y: float
    relayout_applied: bool = False
    relayout_reason: str = ""


@dataclass
class LayoutMetrics:
    score: int
    issues: list[str]
    warnings: list[str]
    overlaps: list[str]
    overlap_safety: dict[str, Any]
    panel_padding_balance: dict[str, Any]
    alignment_consistency: dict[str, Any]
    group_size_normalization: dict[str, Any]
    edge_routing_quality: dict[str, Any]
    anchor_consistency: dict[str, Any]
    visual_hierarchy: dict[str, Any]
    text_style_consistency: dict[str, Any]
    text_containment: dict[str, Any]
    semantic_layout_contract: dict[str, Any]
    inter_panel_gap: dict[str, Any]
    connector_arrow_length: dict[str, Any]
    canvas_utilization: dict[str, Any]
    panel_layout_contract: dict[str, Any]
    text_overflows: list[str]
    alignment_deltas: dict[str, float]
    readability_passed: bool


@dataclass
class PostRenderMetrics:
    svg_bbox_passed: bool
    svg_bbox: dict[str, float]
    svg_bbox_issues: list[str]
    graphviz_json_passed: bool
    graphviz_json: dict[str, Any]
    graphviz_json_issues: list[str]
    png_edge_passed: bool
    png_edge_stats: dict[str, Any]
    png_edge_issues: list[str]


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _char_units(char: str) -> float:
    if char == " ":
        return 0.35
    if _is_cjk(char):
        return 1.0
    if char in "ilI1.,:;|'":
        return 0.32
    if char in "mwMW@#%&":
        return 0.95
    return 0.6


REGULAR_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BOLD_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


@lru_cache(maxsize=128)
def _font(font_size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = BOLD_FONT_PATH if bold else REGULAR_FONT_PATH
    try:
        return ImageFont.truetype(str(path), font_size)
    except OSError:
        return ImageFont.load_default()


def measure_text_width(text: str, font_size: int, *, bold: bool = False) -> float:
    """Measure rendered text, with a conservative SVG-substitution allowance."""
    if not text:
        return 0.0
    bbox = _font(font_size, bold).getbbox(text)
    return max(0.0, float(bbox[2] - bbox[0])) * 1.035


def box_text_width(node_id: str, width: float) -> float:
    """Reserve a dedicated icon column so icons can never cover box copy."""
    return width - (76 if BOX_ICON_BY_ID.get(node_id) and width >= 300 else 36)


def box_text_center_x(box: Box) -> float:
    if BOX_ICON_BY_ID.get(box.id) and box.w >= 300:
        left = box.x + 58
        right = box.x + box.w - 18
        return (left + right) / 2
    return box.x + box.w / 2


def _wrap_hard(text: str, max_units: float) -> list[str]:
    lines: list[str] = []
    current = ""
    units = 0.0
    for ch in text:
        width = _char_units(ch)
        if current and units + width > max_units:
            lines.append(current)
            current = ch
            units = width
        else:
            current += ch
            units += width
    if current:
        lines.append(current)
    return lines


def _wrap_line(text: str, max_units: float) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    units = 0.0
    for word in words:
        word_units = sum(_char_units(ch) for ch in word)
        extra = 0.35 if current else 0.0
        if current and units + extra + word_units > max_units:
            lines.append(current)
            current = word
            units = word_units
        elif not current and word_units > max_units:
            hard = _wrap_hard(word, max_units)
            lines.extend(hard[:-1])
            current = hard[-1]
            units = sum(_char_units(ch) for ch in current)
        else:
            current = f"{current} {word}".strip()
            units += extra + word_units
    if current:
        lines.append(current)
    return lines


def wrap_text(text: str, width_px: float, font_size: int) -> list[str]:
    wrapped: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            wrapped.append("")
            continue
        words = line.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if measure_text_width(candidate, font_size) <= width_px:
                current = candidate
                continue
            if current:
                wrapped.append(current)
                current = ""
            if measure_text_width(word, font_size) <= width_px:
                current = word
                continue
            fragment = ""
            for char in word:
                candidate = fragment + char
                if fragment and measure_text_width(candidate, font_size) > width_px:
                    wrapped.append(fragment)
                    fragment = char
                else:
                    fragment = candidate
            current = fragment
        if current:
            wrapped.append(current)
    return wrapped


def text_height(lines: list[str], font_size: int, line_gap: float = 1.34) -> float:
    return len(lines) * font_size * line_gap


def draw_multiline_text(
    x: float,
    y: float,
    width: float,
    text: str,
    *,
    font_size: int,
    font_weight: str = "500",
    fill: str = "#22314f",
    anchor: str = "middle",
    italic: bool = False,
) -> str:
    lines = wrap_text(text, width, font_size)
    if not lines:
        lines = [""]
    line_h = font_size * 1.34
    total_h = text_height(lines, font_size)
    top = y - total_h / 2 + font_size
    spans = []
    for idx, line in enumerate(lines):
        dy = 0 if idx == 0 else line_h
        spans.append(
            f'<tspan x="{x:.1f}" dy="{dy:.1f}">{escape(line) if line else " "}</tspan>'
        )
    style = "font-style: italic;" if italic else ""
    return (
        f'<text x="{x:.1f}" y="{top:.1f}" text-anchor="{anchor}" '
        f'font-family="Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif" '
        f'font-size="{font_size}" font-weight="{font_weight}" fill="{fill}" '
        f'style="{style}">' + "".join(spans) + "</text>"
    )


def draw_box(box: Box, *, shadow: bool = False) -> str:
    shadow_el = (
        f'<rect x="{box.x + 7:.1f}" y="{box.y + 9:.1f}" width="{box.w:.1f}" '
        f'height="{box.h:.1f}" rx="{box.rx:.1f}" fill="#d9e2f5" opacity="0.34"/>'
    )
    rect = (
        f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
        f'rx="{box.rx:.1f}" fill="{box.fill}" fill-opacity="0.88" stroke="{box.stroke}" '
        f'stroke-width="{box.stroke_width:.1f}" opacity="0.98"/>'
    )
    icon = draw_box_icon(box)
    text = draw_multiline_text(
        box_text_center_x(box),
        box.y + box.h / 2,
        box_text_width(box.id, box.w),
        box.text,
        font_size=box.font_size,
    )
    return (shadow_el if shadow else "") + rect + icon + text


def draw_box_icon(box: Box) -> str:
    icon = BOX_ICON_BY_ID.get(box.id)
    if not icon or box.w < 300:
        return ""
    x = box.x + 20
    y = box.y + 20
    color = box.stroke
    common = f'stroke="{color}" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" fill="none" opacity="0.84"'
    if icon == "source":
        return (
            f'<g {common}><rect x="{x:.1f}" y="{y:.1f}" width="18" height="22" rx="2"/>'
            f'<path d="M{x+5:.1f} {y+7:.1f}h8M{x+5:.1f} {y+12:.1f}h8M{x+5:.1f} {y+17:.1f}h5"/></g>'
        )
    if icon == "merge":
        return (
            f'<g {common}><path d="M{x:.1f} {y+4:.1f}h10v18h12"/>'
            f'<path d="M{x+22:.1f} {y+4:.1f}h-10v18"/></g>'
        )
    if icon == "filter":
        return f'<path d="M{x:.1f} {y:.1f}h24l-9 11v9l-6 4v-13z" {common}/>'
    if icon == "check":
        return (
            f'<g {common}><path d="M{x+12:.1f} {y:.1f}l10 5v8c0 7-4 11-10 14C{x+6:.1f} {y+24:.1f} {x+2:.1f} {y+20:.1f} {x+2:.1f} {y+13:.1f}v-8z"/>'
            f'<path d="M{x+7:.1f} {y+14:.1f}l4 4 7-8"/></g>'
        )
    if icon == "exclude":
        return (
            f'<g {common}><circle cx="{x+12:.1f}" cy="{y+12:.1f}" r="11"/>'
            f'<path d="M{x+5:.1f} {y+19:.1f}l14-14"/></g>'
        )
    if icon == "cite":
        return (
            f'<g {common}><circle cx="{x+7:.1f}" cy="{y+8:.1f}" r="5"/>'
            f'<circle cx="{x+18:.1f}" cy="{y+17:.1f}" r="5"/>'
            f'<path d="M{x+11:.1f} {y+11:.1f}l4 3"/></g>'
        )
    if icon == "trend":
        return f'<path d="M{x:.1f} {y+22:.1f}h24M{x+2:.1f} {y+18:.1f}l6-7 5 4 8-11" {common}/>'
    if icon == "network":
        return (
            f'<g {common}><circle cx="{x+5:.1f}" cy="{y+7:.1f}" r="4"/>'
            f'<circle cx="{x+18:.1f}" cy="{y+5:.1f}" r="4"/>'
            f'<circle cx="{x+15:.1f}" cy="{y+20:.1f}" r="4"/>'
            f'<path d="M{x+9:.1f} {y+6:.1f}l5-1M{x+8:.1f} {y+10:.1f}l5 7M{x+17:.1f} {y+9:.1f}l-1 7"/></g>'
        )
    if icon == "topic":
        return (
            f'<g {common}><circle cx="{x+12:.1f}" cy="{y+12:.1f}" r="10"/>'
            f'<path d="M{x+12:.1f} {y+2:.1f}v20M{x+2:.1f} {y+12:.1f}h20"/></g>'
        )
    return ""


def draw_label_pill(x: float, y: float, w: float, h: float, text: str, font_size: int, rx: float) -> str:
    rect = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" '
        f'fill="#d9ebff" stroke="#72a8eb" stroke-width="2.2"/>'
    )
    text_el = (
        f'<g transform="translate({x + w / 2:.1f},{y + h / 2:.1f}) rotate(-90)">'
        f'<text x="0" y="10" text-anchor="middle" '
        f'font-family="Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif" '
        f'font-size="{font_size}" font-weight="700" fill="#294a85">{escape(text)}</text>'
        f"</g>"
    )
    return rect + text_el


def draw_panel(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    title: str | None = None,
    font_size: int = 23,
    rx: float = 18,
) -> str:
    panel = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" '
        f'fill="none" stroke="#78a7ea" stroke-width="2.4" '
        f'stroke-dasharray="8 7" opacity="0.9"/>'
    )
    if not title:
        return panel
    return panel + draw_multiline_text(
        x + w / 2,
        y + h - 22,
        w - 50,
        title,
        font_size=font_size,
        font_weight="700",
        italic=True,
    )


def draw_large_arrow(x1: float, y: float, x2: float) -> str:
    body_h = 24
    head_len = 38
    points = [
        (x1, y - body_h / 2),
        (x2 - head_len, y - body_h / 2),
        (x2 - head_len, y - 28),
        (x2, y),
        (x2 - head_len, y + 28),
        (x2 - head_len, y + body_h / 2),
        (x1, y + body_h / 2),
    ]
    serialized = " ".join(f"{x:.1f},{yy:.1f}" for x, yy in points)
    return f'<polygon points="{serialized}" fill="#8ab2ef" opacity="0.95"/>'


def _panel_right(panel: tuple[float, float, float, float]) -> float:
    return panel[0] + panel[2]


def _inter_panel_gap(layout: LayoutResult) -> float:
    return layout.right_panel[0] - _panel_right(layout.left_panel)


def _big_arrow_bounds(layout: LayoutResult) -> tuple[float, float]:
    tail_x = _panel_right(layout.left_panel) + BIG_ARROW_TAIL_INSET
    tip_x = layout.right_panel[0] - BIG_ARROW_TIP_INSET
    return tail_x, tip_x


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def draw_line(x1: float, y1: float, x2: float, y2: float, stroke_width: float = 2.6) -> str:
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{CONNECTOR_COLOR}" stroke-width="{stroke_width:.1f}" stroke-linecap="round"/>'
    )


def draw_polyline(points: list[tuple[float, float]], stroke_width: float = 2.6) -> str:
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (
        f'<polyline points="{serialized}" fill="none" '
        f'stroke="{CONNECTOR_COLOR}" stroke-width="{stroke_width:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
    )


def _arrow_head(x1: float, y1: float, x2: float, y2: float, head_len: float = 18) -> str:
    angle = math.atan2(y2 - y1, x2 - x1)
    left = (
        x2 - head_len * math.cos(angle - math.pi / 7),
        y2 - head_len * math.sin(angle - math.pi / 7),
    )
    right = (
        x2 - head_len * math.cos(angle + math.pi / 7),
        y2 - head_len * math.sin(angle + math.pi / 7),
    )
    return (
        f'<polygon points="{x2:.1f},{y2:.1f} {left[0]:.1f},{left[1]:.1f} '
        f'{right[0]:.1f},{right[1]:.1f}" fill="{CONNECTOR_COLOR}"/>'
    )


def draw_arrow_polyline(points: list[tuple[float, float]], stroke_width: float = 2.8) -> str:
    if len(points) < 2:
        return ""
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    (x1, y1), (x2, y2) = points[-2], points[-1]
    return (
        f'<polyline points="{serialized}" fill="none" '
        f'stroke="{CONNECTOR_COLOR}" stroke-width="{stroke_width:.1f}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        + _arrow_head(x1, y1, x2, y2, 16)
    )


def fit_box(
    node_id: str,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    font_size: int,
    min_font_size: int | None = None,
) -> Box:
    if min_font_size is None:
        min_font_size = max(14, font_size - 2)
    chosen = font_size
    for size in range(font_size, min_font_size - 1, -1):
        lines = wrap_text(text, box_text_width(node_id, w), size)
        if text_height(lines, size) <= h - BODY_TEXT_PAD_Y:
            chosen = size
            break
        chosen = size
    return Box(x=x, y=y, w=w, h=h, text=text, font_size=chosen, id=node_id)


def validate_boxes(boxes: list[Box]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    overlaps: list[str] = []
    for box in boxes:
        lines = wrap_text(box.text, box_text_width(box.id, box.w), box.font_size)
        if text_height(lines, box.font_size) > box.h - BODY_TEXT_PAD_Y:
            issues.append(f"text overflow in {box.id}")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a = boxes[i]
            b = boxes[j]
            overlap_x = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
            overlap_y = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
            if overlap_x > BOX_GAP_TOLERANCE and overlap_y > BOX_GAP_TOLERANCE:
                desc = f"{a.id} overlaps {b.id}"
                issues.append(desc)
                overlaps.append(desc)
    return issues, overlaps


def check_text_containment(layout: LayoutResult) -> dict[str, Any]:
    """Hard gate every measured line against its box and the icon reserve."""
    checks: list[dict[str, Any]] = []
    violations: list[str] = []
    for box_id, box in layout.boxes.items():
        icon_reserved = bool(BOX_ICON_BY_ID.get(box_id) and box.w >= 300)
        inner_left = box.x + (58 if icon_reserved else 18)
        inner_right = box.x + box.w - 18
        inner_top = box.y + 16
        inner_bottom = box.y + box.h - 16
        available_width = inner_right - inner_left
        lines = wrap_text(box.text, available_width, box.font_size)
        line_widths = [measure_text_width(line, box.font_size) for line in lines]
        rendered_width = max(line_widths, default=0.0)
        rendered_height = text_height(lines, box.font_size)
        center_x = (inner_left + inner_right) / 2
        text_bbox = (
            center_x - rendered_width / 2,
            box.y + box.h / 2 - rendered_height / 2,
            rendered_width,
            rendered_height,
        )
        horizontal_passed = rendered_width <= available_width + 0.01
        vertical_passed = rendered_height <= inner_bottom - inner_top + 0.01
        icon_clearance_passed = True
        if icon_reserved:
            icon_rect = (box.x + 16, box.y + 16, 34, 34)
            icon_clearance_passed = not _rects_overlap(icon_rect, text_bbox, pad=2)
        passed = horizontal_passed and vertical_passed and icon_clearance_passed
        if not passed:
            violations.append(f"measured text containment failed in {box_id}")
        checks.append(
            {
                "node": box_id,
                "font_size_px": box.font_size,
                "line_count": len(lines),
                "available_width_px": round(available_width, 2),
                "max_rendered_line_width_px": round(rendered_width, 2),
                "available_height_px": round(inner_bottom - inner_top, 2),
                "rendered_text_height_px": round(rendered_height, 2),
                "icon_column_reserved": icon_reserved,
                "horizontal_passed": horizontal_passed,
                "vertical_passed": vertical_passed,
                "icon_clearance_passed": icon_clearance_passed,
                "passed": passed,
            }
        )
    return {
        "measurement_engine": "Pillow/DejaVu Sans getbbox with 3.5% SVG substitution allowance",
        "passed": not violations,
        "violations": violations,
        "checks": checks,
    }


def _rect_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float]:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    gap_x = max(bx - (ax + aw), ax - (bx + bw), 0.0)
    gap_y = max(by - (ay + ah), ay - (by + bh), 0.0)
    return gap_x, gap_y


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], *, pad: float = 0.0) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + pad <= bx
        or bx + bw + pad <= ax
        or ay + ah + pad <= by
        or by + bh + pad <= ay
    )


def check_overlap_safety(layout: LayoutResult) -> dict[str, Any]:
    issues: list[str] = []
    stage_checks: list[dict[str, Any]] = []
    box_rects = {
        box_id: (box.x, box.y, box.w, box.h)
        for box_id, box in layout.boxes.items()
    }

    stage_targets = {
        "identification": ["strategy_one", "strategy_two"],
        "screening": ["total_box", "duplicate_label", "manual_box", "excluded_box"],
        "included": ["analysis_box", "citation_box"],
    }
    for stage, rect in STAGE_PILLS.items():
        for box_id in stage_targets[stage]:
            gap_x, gap_y = _rect_gap(rect, box_rects[box_id])
            overlaps = _rects_overlap(rect, box_rects[box_id], pad=BOX_SAFE_GAP)
            stage_checks.append(
                {
                    "stage": stage,
                    "box": box_id,
                    "gap_x": round(gap_x, 2),
                    "gap_y": round(gap_y, 2),
                    "passed": not overlaps,
                }
            )
            if overlaps:
                issues.append(f"stage label {stage} overlaps or crowds {box_id}")

    # Icons are placed at the top-left of wide boxes only; keep a reserved zone
    # clear of the text center so decorative symbols never cover copy.
    for box_id, box in layout.boxes.items():
        if BOX_ICON_BY_ID.get(box_id) and box.w >= 300:
            icon_rect = (box.x + 16, box.y + 16, 34, 34)
            text_rect = (box.x + 58, box.y + 18, box.w - 76, box.h - 36)
            if _rects_overlap(icon_rect, text_rect, pad=2):
                issues.append(f"icon crowds text in {box_id}")

    return {
        "passed": not issues,
        "issues": issues,
        "stage_label_checks": stage_checks,
    }


def check_panel_padding_balance(layout: LayoutResult) -> dict[str, Any]:
    left_x, _, left_w, _ = layout.left_panel
    panel_right = left_x + left_w
    content_left = min(rect[0] for rect in STAGE_PILLS.values())
    left_content_box_ids = [
        "strategy_one",
        "strategy_two",
        "total_box",
        "duplicate_label",
        "manual_box",
        "excluded_box",
        "analysis_box",
        "citation_box",
    ]
    content_right = max(
        layout.boxes[box_id].x + layout.boxes[box_id].w
        for box_id in left_content_box_ids
    )
    left_padding = content_left - left_x
    right_padding = panel_right - content_right
    delta = abs(left_padding - right_padding)
    passed = delta <= PANEL_PADDING_BALANCE_TOLERANCE
    issues = [] if passed else [
        (
            "left panel horizontal padding is imbalanced: "
            f"left={left_padding:.1f}, right={right_padding:.1f}, delta={delta:.1f}"
        )
    ]
    return {
        "passed": passed,
        "issues": issues,
        "left_padding": round(left_padding, 2),
        "right_padding": round(right_padding, 2),
        "delta": round(delta, 2),
        "tolerance": PANEL_PADDING_BALANCE_TOLERANCE,
        "content_left": round(content_left, 2),
        "content_right": round(content_right, 2),
    }


def _box_rect(box: Box, *, pad: float = 0.0) -> tuple[float, float, float, float]:
    return (box.x - pad, box.y - pad, box.w + pad * 2, box.h + pad * 2)


def _box_center(box: Box) -> tuple[float, float]:
    return (box.x + box.w / 2, box.y + box.h / 2)


def _nearly_equal(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _edge_paths(layout: LayoutResult) -> dict[str, list[tuple[float, float]]]:
    boxes = layout.boxes
    total = boxes["total_box"]
    manual = boxes["manual_box"]
    analysis = boxes["analysis_box"]
    citation = boxes["citation_box"]
    strategy1 = boxes["strategy_one"]
    strategy2 = boxes["strategy_two"]
    duplicate = boxes["duplicate_label"]
    excluded = boxes["excluded_box"]

    shared_merge_y = total.y - 28
    duplicate_branch_y = duplicate.y + duplicate.h / 2
    excluded_branch_y = manual.y + manual.h + 36
    return {
        "strategy_one_to_total": [
            (strategy1.x + strategy1.w / 2, strategy1.y + strategy1.h),
            (strategy1.x + strategy1.w / 2, shared_merge_y),
            (total.x + total.w / 2, shared_merge_y),
            (total.x + total.w / 2, total.y),
        ],
        "strategy_two_to_total": [
            (strategy2.x + strategy2.w / 2, strategy2.y + strategy2.h),
            (strategy2.x + strategy2.w / 2, shared_merge_y),
            (total.x + total.w / 2, shared_merge_y),
            (total.x + total.w / 2, total.y),
        ],
        "total_to_manual": [
            (total.x + total.w / 2, total.y + total.h),
            (manual.x + manual.w / 2, manual.y),
        ],
        "total_to_duplicate": [
            (total.x + total.w / 2, duplicate_branch_y),
            (duplicate.x, duplicate_branch_y),
        ],
        "manual_to_excluded": [
            (manual.x + manual.w / 2, excluded_branch_y),
            (excluded.x, excluded_branch_y),
        ],
        "manual_to_analysis": [
            (manual.x + manual.w / 2, manual.y + manual.h),
            (analysis.x + analysis.w / 2, analysis.y),
        ],
        "analysis_to_citation": [
            (analysis.x + analysis.w, analysis.y + analysis.h / 2),
            (citation.x, analysis.y + analysis.h / 2),
        ],
    }


def _segments(points: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return list(zip(points, points[1:]))


def _point_in_rect(point: tuple[float, float], rect: tuple[float, float, float, float]) -> bool:
    x, y = point
    rx, ry, rw, rh = rect
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def _segment_intersects_rect(
    a: tuple[float, float],
    b: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> bool:
    rx, ry, rw, rh = rect
    corners = [(rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    return _point_in_rect(a, rect) or _point_in_rect(b, rect) or any(
        _segments_cross(a, b, c, d) for c, d in edges
    )


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    # Proper crossing only. Shared endpoints and collinear overlaps are route sharing, not visual crossing.
    if a in {c, d} or b in {c, d}:
        return False
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def check_alignment_consistency(layout: LayoutResult) -> dict[str, Any]:
    boxes = layout.boxes
    row_errors: list[str] = []
    column_errors: list[str] = []
    gap_values: list[float] = []
    size_values: list[float] = []

    top_sources = [boxes["strategy_one"], boxes["strategy_two"]]
    if not _nearly_equal(top_sources[0].y, top_sources[1].y, ALIGNMENT_TOLERANCE):
        row_errors.append("top source boxes are not top-aligned")
    if not _nearly_equal(top_sources[0].h, top_sources[1].h, SIZE_VARIANCE_TOLERANCE):
        row_errors.append("top source boxes have inconsistent heights")
    gap_values.append(top_sources[1].x - (top_sources[0].x + top_sources[0].w))
    size_values.extend([box.w for box in top_sources] + [box.h for box in top_sources])

    main_spine = [boxes["total_box"], boxes["manual_box"], boxes["analysis_box"]]
    centers = [_box_center(box)[0] for box in main_spine]
    if max(centers) - min(centers) > ALIGNMENT_TOLERANCE:
        column_errors.append("main process spine center_x is inconsistent")

    analysis_cards = [boxes[box_id] for box_id in layout.analysis_order]
    analysis_lefts = [box.x for box in analysis_cards]
    analysis_widths = [box.w for box in analysis_cards]
    analysis_gaps = [
        analysis_cards[idx + 1].y - (analysis_cards[idx].y + analysis_cards[idx].h)
        for idx in range(len(analysis_cards) - 1)
    ]
    if max(analysis_lefts) - min(analysis_lefts) > ALIGNMENT_TOLERANCE:
        column_errors.append("analysis panel cards are not left-aligned")
    if max(analysis_widths) - min(analysis_widths) > SIZE_VARIANCE_TOLERANCE:
        row_errors.append("analysis panel cards have inconsistent widths")
    gap_values.extend(analysis_gaps)
    size_values.extend(analysis_widths)

    gap_variance = _variance(gap_values)
    size_variance = _variance(size_values)
    if gap_variance > GAP_VARIANCE_TOLERANCE**2:
        row_errors.append(f"group gap variance too high: {gap_variance:.2f}")
    passed = not row_errors and not column_errors
    return {
        "passed": passed,
        "row_alignment_errors": row_errors,
        "column_alignment_errors": column_errors,
        "gap_variance": round(gap_variance, 2),
        "size_variance": round(size_variance, 2),
    }


def check_group_size_normalization(layout: LayoutResult) -> dict[str, Any]:
    boxes = layout.boxes
    violations: list[str] = []
    groups = [
        {"id": "top_sources", "members": ["strategy_one", "strategy_two"], "equal_width": True, "equal_height": True},
        {"id": "analysis_cards", "members": layout.analysis_order, "equal_width": True, "equal_height": True},
        {"id": "side_exclusion_cards", "members": ["duplicate_label", "excluded_box"], "equal_x": True},
    ]
    details: list[dict[str, Any]] = []
    for group in groups:
        members = [boxes[member] for member in group["members"]]
        widths = [box.w for box in members]
        heights = [box.h for box in members]
        xs = [box.x for box in members]
        group_violations: list[str] = []
        if group.get("equal_width") and max(widths) - min(widths) > SIZE_VARIANCE_TOLERANCE:
            group_violations.append("widths differ")
        if group.get("equal_height") and max(heights) - min(heights) > SIZE_VARIANCE_TOLERANCE:
            group_violations.append("heights differ")
        if group.get("equal_x") and max(xs) - min(xs) > ALIGNMENT_TOLERANCE:
            group_violations.append("x positions differ")
        violations.extend(f"{group['id']}: {violation}" for violation in group_violations)
        details.append(
            {
                "id": group["id"],
                "members": group["members"],
                "width_range": round(max(widths) - min(widths), 2),
                "height_range": round(max(heights) - min(heights), 2),
                "x_range": round(max(xs) - min(xs), 2),
                "passed": not group_violations,
            }
        )
    return {"passed": not violations, "violations": violations, "groups": details}


def check_edge_routing_quality(layout: LayoutResult) -> dict[str, Any]:
    paths = _edge_paths(layout)
    boxes = layout.boxes
    node_crossing_edges: list[str] = []
    bad_direction_edges: list[str] = []
    all_segments: list[tuple[str, tuple[float, float], tuple[float, float]]] = []

    edge_endpoints = {
        "strategy_one_to_total": {"strategy_one", "total_box"},
        "strategy_two_to_total": {"strategy_two", "total_box"},
        "total_to_manual": {"total_box", "manual_box"},
        "total_to_duplicate": {"total_box", "duplicate_label"},
        "manual_to_excluded": {"manual_box", "excluded_box"},
        "manual_to_analysis": {"manual_box", "analysis_box"},
        "analysis_to_citation": {"analysis_box", "citation_box"},
    }
    for edge_id, points in paths.items():
        for a, b in _segments(points):
            all_segments.append((edge_id, a, b))
            for box_id, box in boxes.items():
                if box_id in edge_endpoints[edge_id]:
                    continue
                if _segment_intersects_rect(a, b, _box_rect(box, pad=2)):
                    node_crossing_edges.append(f"{edge_id} crosses {box_id}")

    for edge_id in ["total_to_manual", "manual_to_analysis"]:
        points = paths[edge_id]
        if points[-1][1] <= points[0][1]:
            bad_direction_edges.append(f"{edge_id} is not monotonic downward")
    for edge_id in ["total_to_duplicate", "manual_to_excluded", "analysis_to_citation"]:
        points = paths[edge_id]
        if points[-1][0] <= points[0][0]:
            bad_direction_edges.append(f"{edge_id} is not monotonic rightward")

    crossing_count = 0
    crossing_pairs: list[str] = []
    for idx, (edge_a, a1, a2) in enumerate(all_segments):
        for edge_b, b1, b2 in all_segments[idx + 1 :]:
            if edge_a == edge_b:
                continue
            if _segments_cross(a1, a2, b1, b2):
                crossing_count += 1
                crossing_pairs.append(f"{edge_a} x {edge_b}")

    passed = not node_crossing_edges and not bad_direction_edges and crossing_count <= MAX_EDGE_CROSSINGS
    return {
        "passed": passed,
        "node_crossing_edges": sorted(set(node_crossing_edges)),
        "edge_crossing_count": crossing_count,
        "edge_crossing_pairs": crossing_pairs,
        "bad_feedback_edges": [],
        "bad_direction_edges": bad_direction_edges,
        "max_edge_crossings": MAX_EDGE_CROSSINGS,
    }


def check_anchor_consistency(layout: LayoutResult) -> dict[str, Any]:
    boxes = layout.boxes
    paths = _edge_paths(layout)
    violations: list[str] = []

    expected = {
        "strategy_one_to_total": ((boxes["strategy_one"].x + boxes["strategy_one"].w / 2, boxes["strategy_one"].y + boxes["strategy_one"].h), (boxes["total_box"].x + boxes["total_box"].w / 2, boxes["total_box"].y)),
        "strategy_two_to_total": ((boxes["strategy_two"].x + boxes["strategy_two"].w / 2, boxes["strategy_two"].y + boxes["strategy_two"].h), (boxes["total_box"].x + boxes["total_box"].w / 2, boxes["total_box"].y)),
        "total_to_manual": ((boxes["total_box"].x + boxes["total_box"].w / 2, boxes["total_box"].y + boxes["total_box"].h), (boxes["manual_box"].x + boxes["manual_box"].w / 2, boxes["manual_box"].y)),
        "manual_to_analysis": ((boxes["manual_box"].x + boxes["manual_box"].w / 2, boxes["manual_box"].y + boxes["manual_box"].h), (boxes["analysis_box"].x + boxes["analysis_box"].w / 2, boxes["analysis_box"].y)),
        "analysis_to_citation": ((boxes["analysis_box"].x + boxes["analysis_box"].w, boxes["analysis_box"].y + boxes["analysis_box"].h / 2), (boxes["citation_box"].x, boxes["analysis_box"].y + boxes["analysis_box"].h / 2)),
    }
    for edge_id, (start, end) in expected.items():
        points = paths[edge_id]
        if not (_nearly_equal(points[0][0], start[0], ALIGNMENT_TOLERANCE) and _nearly_equal(points[0][1], start[1], ALIGNMENT_TOLERANCE)):
            violations.append(f"{edge_id} source anchor is inconsistent")
        if not (_nearly_equal(points[-1][0], end[0], ALIGNMENT_TOLERANCE) and _nearly_equal(points[-1][1], end[1], ALIGNMENT_TOLERANCE)):
            violations.append(f"{edge_id} target anchor is inconsistent")
    return {"passed": not violations, "violations": violations}


def check_visual_hierarchy(layout: LayoutResult) -> dict[str, Any]:
    warnings: list[str] = []
    title_center_delta = 0.0
    if layout.left_panel[0] >= layout.right_panel[0]:
        warnings.append("analysis panel is not right of collection panel")
    if layout.right_panel[2] < 360:
        warnings.append("analysis panel is too narrow")
    if BOX_STYLE_BY_ID["manual_box"] != BOX_STYLE_BY_ID["analysis_box"]:
        warnings.append("included/process nodes do not share color semantics")
    if BOX_STYLE_BY_ID["duplicate_label"] != BOX_STYLE_BY_ID["citation_box"]:
        warnings.append("support/annotation nodes do not share color semantics")
    analysis_cards = [layout.boxes[box_id] for box_id in layout.analysis_order]
    if max(box.w for box in analysis_cards) - min(box.w for box in analysis_cards) > SIZE_VARIANCE_TOLERANCE:
        warnings.append("analysis panel cards are not visually normalized")
    return {
        "passed": not warnings,
        "warnings": warnings,
        "title_center_delta": title_center_delta,
        "color_semantics": {
            "strategy": BOX_STYLE_BY_ID["strategy_one"],
            "included": BOX_STYLE_BY_ID["manual_box"],
            "annotation": BOX_STYLE_BY_ID["duplicate_label"],
            "excluded": BOX_STYLE_BY_ID["excluded_box"],
        },
    }


def check_text_style_consistency(layout: LayoutResult) -> dict[str, Any]:
    long_line_nodes: list[str] = []
    orphan_line_nodes: list[str] = []
    font_mismatch_nodes: list[str] = []
    line_counts: dict[str, int] = {}

    expected_fonts = {
        "strategy_one": layout.boxes["strategy_one"].font_size,
        "strategy_two": layout.boxes["strategy_one"].font_size,
        "analysis_step_1": layout.boxes["analysis_step_1"].font_size,
        "analysis_step_2": layout.boxes["analysis_step_1"].font_size,
        "analysis_step_3": layout.boxes["analysis_step_1"].font_size,
        "analysis_step_4": layout.boxes["analysis_step_1"].font_size,
    }
    for box_id, box in layout.boxes.items():
        lines = wrap_text(box.text, box_text_width(box.id, box.w), box.font_size)
        line_counts[box_id] = len(lines)
        if any(sum(_char_units(ch) for ch in line) > MAX_TEXT_LINE_UNITS for line in lines):
            long_line_nodes.append(box_id)
        last_words = lines[-1].strip().split() if lines else []
        if last_words and len(lines) > 2:
            last_units = sum(_char_units(ch) for ch in lines[-1].strip())
            if last_units <= 2.0 or lines[-1].strip().lower() in {"and", "or", "of", "ai"}:
                orphan_line_nodes.append(box_id)
        expected_font = expected_fonts.get(box_id)
        if expected_font is not None and abs(box.font_size - expected_font) > 2:
            font_mismatch_nodes.append(box_id)

    passed = not long_line_nodes and not orphan_line_nodes and not font_mismatch_nodes
    return {
        "passed": passed,
        "long_line_nodes": long_line_nodes,
        "orphan_line_nodes": orphan_line_nodes,
        "font_mismatch_nodes": font_mismatch_nodes,
        "line_counts": line_counts,
        "max_text_line_units": MAX_TEXT_LINE_UNITS,
    }


def check_semantic_layout_contract(layout: LayoutResult) -> dict[str, Any]:
    boxes = layout.boxes
    violations: list[str] = []

    if not (STAGE_PILLS["identification"][1] < STAGE_PILLS["screening"][1] < STAGE_PILLS["included"][1]):
        violations.append("stage labels are not ordered identification -> screening -> included")
    if layout.right_panel[0] <= layout.left_panel[0] + layout.left_panel[2]:
        violations.append("analysis panel is not right of data collection panel")
    if boxes["duplicate_label"].x <= boxes["total_box"].x + boxes["total_box"].w:
        violations.append("duplicate exclusion label is not right of total publications node")
    if boxes["excluded_box"].x <= boxes["manual_box"].x + boxes["manual_box"].w:
        violations.append("excluded-publications detail is not right of manual-screening node")
    if boxes["analysis_box"].y <= boxes["manual_box"].y:
        violations.append("data-analysis node is not below manual-screening node")
    if boxes["analysis_box"].y + boxes["analysis_box"].h < boxes["excluded_box"].y:
        violations.append("final included node is not visually below screening exclusions")
    if boxes["citation_box"].x <= boxes["analysis_box"].x + boxes["analysis_box"].w:
        violations.append("citation collection support box is not right of final included node")
    return {"passed": not violations, "violations": violations}


def check_inter_panel_gap(layout: LayoutResult) -> dict[str, Any]:
    gap = _inter_panel_gap(layout)
    min_allowed = max(MIN_INTER_PANEL_GAP, layout.width * MIN_GAP_SHARE)
    max_allowed = min(MAX_INTER_PANEL_GAP, layout.width * MAX_INTER_PANEL_GAP_RATIO)
    issues: list[str] = []
    repair = None

    if gap < min_allowed:
        issues.append(f"inter-panel gap is too tight: {gap:.1f}px < {min_allowed:.1f}px")
        repair = "move_analysis_panel_right"
    if gap > max_allowed:
        issues.append(f"inter-panel gap is too loose: {gap:.1f}px > {max_allowed:.1f}px")
        repair = "move_analysis_panel_left"

    return {
        "passed": not issues,
        "issues": issues,
        "gap_px": round(gap, 2),
        "min_allowed_px": round(min_allowed, 2),
        "max_allowed_px": round(max_allowed, 2),
        "repair": repair,
    }


def check_connector_arrow_length(layout: LayoutResult) -> dict[str, Any]:
    tail_x, tip_x = _big_arrow_bounds(layout)
    length = tip_x - tail_x
    max_allowed = min(MAX_BIG_ARROW_LENGTH, max(0.0, _inter_panel_gap(layout) * 0.75))
    issues: list[str] = []
    repair = None

    if length < MIN_BIG_ARROW_LENGTH:
        issues.append(f"connector arrow is too short: {length:.1f}px < {MIN_BIG_ARROW_LENGTH:.1f}px")
        repair = "increase_panel_gap"
    if length > max_allowed:
        issues.append(f"connector arrow is too long: {length:.1f}px > {max_allowed:.1f}px")
        repair = "move_analysis_panel_left"

    return {
        "passed": not issues,
        "issues": issues,
        "length_px": round(length, 2),
        "min_px": MIN_BIG_ARROW_LENGTH,
        "preferred_px": PREFERRED_BIG_ARROW_LENGTH,
        "max_allowed_px": round(max_allowed, 2),
        "tail_x": round(tail_x, 2),
        "tip_x": round(tip_x, 2),
        "repair": repair,
    }


def check_canvas_utilization(layout: LayoutResult) -> dict[str, Any]:
    content_min_x = min(layout.left_panel[0], layout.right_panel[0])
    content_max_x = max(_panel_right(layout.left_panel), _panel_right(layout.right_panel))
    content_width = content_max_x - content_min_x
    content_width_ratio = content_width / layout.width
    issues: list[str] = []

    if content_width_ratio < MIN_CONTENT_WIDTH_RATIO:
        issues.append(
            f"content width ratio is too sparse: {content_width_ratio:.3f} < {MIN_CONTENT_WIDTH_RATIO:.2f}"
        )
    if content_width_ratio > MAX_CONTENT_WIDTH_RATIO:
        issues.append(
            f"content width ratio is too wide: {content_width_ratio:.3f} > {MAX_CONTENT_WIDTH_RATIO:.2f}"
        )

    return {
        "passed": not issues,
        "issues": issues,
        "content_width_px": round(content_width, 2),
        "content_width_ratio": round(content_width_ratio, 4),
        "min_ratio": MIN_CONTENT_WIDTH_RATIO,
        "max_ratio": MAX_CONTENT_WIDTH_RATIO,
    }


def check_panel_layout_contract(layout: LayoutResult) -> dict[str, Any]:
    violations: list[str] = []
    gap = _inter_panel_gap(layout)
    total_panel_row_width = layout.left_panel[2] + gap + layout.right_panel[2]
    left_share = layout.left_panel[2] / total_panel_row_width
    right_share = layout.right_panel[2] / total_panel_row_width
    gap_share = gap / total_panel_row_width
    expected_gap = _clamp(layout.width * 0.05, 64.0, MAX_INTER_PANEL_GAP)

    if layout.right_panel[0] <= _panel_right(layout.left_panel):
        violations.append("analysis panel must be placed to the right of the collection panel")
    if not (MIN_INTER_PANEL_GAP <= gap <= MAX_INTER_PANEL_GAP):
        violations.append(f"panel gap must stay between {MIN_INTER_PANEL_GAP:.0f}px and {MAX_INTER_PANEL_GAP:.0f}px")
    if not (MIN_LEFT_PANEL_SHARE <= left_share <= MAX_LEFT_PANEL_SHARE):
        violations.append(
            f"left panel share must be {MIN_LEFT_PANEL_SHARE:.2f}-{MAX_LEFT_PANEL_SHARE:.2f}, got {left_share:.3f}"
        )
    if not (MIN_RIGHT_PANEL_SHARE <= right_share <= MAX_RIGHT_PANEL_SHARE):
        violations.append(
            f"right panel share must be {MIN_RIGHT_PANEL_SHARE:.2f}-{MAX_RIGHT_PANEL_SHARE:.2f}, got {right_share:.3f}"
        )
    if not (MIN_GAP_SHARE <= gap_share <= MAX_GAP_SHARE):
        violations.append(f"gap share must be {MIN_GAP_SHARE:.2f}-{MAX_GAP_SHARE:.2f}, got {gap_share:.3f}")

    return {
        "passed": not violations,
        "violations": violations,
        "left_panel_right": round(_panel_right(layout.left_panel), 2),
        "right_panel_left": round(layout.right_panel[0], 2),
        "gap_px": round(gap, 2),
        "expected_gap_px": round(expected_gap, 2),
        "left_panel_share": round(left_share, 4),
        "right_panel_share": round(right_share, 4),
        "gap_share": round(gap_share, 4),
    }


def build_ir(spec: dict[str, Any]) -> DiagramIR:
    nodes = [
        NodeSpec("strategy_one", spec["strategy_boxes"][0]["text"], "strategy"),
        NodeSpec("strategy_two", spec["strategy_boxes"][1]["text"], "strategy"),
        NodeSpec("total_box", spec["total_box"], "total"),
        NodeSpec("duplicate_label", spec["duplicate_label"], "side_label"),
        NodeSpec("manual_box", spec["manual_box"], "manual"),
        NodeSpec("excluded_box", spec["excluded_box"], "excluded"),
        NodeSpec("analysis_box", spec["analysis_box"], "analysis"),
        NodeSpec("citation_box", spec["citation_box"], "citation"),
    ]
    for idx, step in enumerate(spec["analysis_steps"], start=1):
        nodes.append(NodeSpec(f"analysis_step_{idx}", step, "analysis_step"))

    edges = [
        EdgeSpec("strategy_one_to_total", "strategy_one", "total_box", "strategy_one_to_total", "flow"),
        EdgeSpec("strategy_two_to_total", "strategy_two", "total_box", "strategy_two_to_total", "flow"),
        EdgeSpec("total_to_manual", "total_box", "manual_box", "total_to_manual", "flow"),
        EdgeSpec("total_to_duplicate", "total_box", "duplicate_label", "total_to_duplicate", "annotation"),
        EdgeSpec("manual_to_excluded", "manual_box", "excluded_box", "manual_to_excluded", "annotation"),
        EdgeSpec("manual_to_analysis", "manual_box", "analysis_box", "manual_to_analysis", "flow"),
        EdgeSpec("analysis_to_citation", "analysis_box", "citation_box", "analysis_to_citation", "annotation"),
        EdgeSpec("analysis_panel_arrow", "analysis_box", "analysis_step_1", "analysis_panel_arrow", "panel_flow"),
    ]

    return DiagramIR(
        title=spec["title"],
        stage_labels=spec["stage_labels"],
        left_caption=spec["left_caption"],
        right_caption=spec["right_caption"],
        nodes=nodes,
        edges=edges,
        analysis_steps=spec["analysis_steps"],
        connector_styles=spec.get("connector_styles") or {},
        layout=spec.get("layout") or {},
    )


def validate_ir(ir: DiagramIR) -> list[str]:
    issues: list[str] = []
    if len(ir.stage_labels) != 3:
        issues.append("stage_labels must contain exactly 3 labels")
    if len([n for n in ir.nodes if n.kind == "strategy"]) != 2:
        issues.append("exactly 2 strategy boxes are required")
    if len(ir.analysis_steps) != 4:
        issues.append("analysis_steps must contain exactly 4 steps")

    node_ids = {node.id for node in ir.nodes}
    required_edges = {
        "strategy_one_to_total",
        "strategy_two_to_total",
        "total_to_manual",
        "total_to_duplicate",
        "manual_to_excluded",
        "manual_to_analysis",
        "analysis_to_citation",
        "analysis_panel_arrow",
    }
    seen_edges = {edge.id for edge in ir.edges}
    missing_edges = sorted(required_edges - seen_edges)
    if missing_edges:
        issues.append("missing edges: " + ", ".join(missing_edges))

    for edge in ir.edges:
        if edge.source not in node_ids:
            issues.append(f"edge {edge.id} has unknown source {edge.source}")
        if edge.target not in node_ids:
            issues.append(f"edge {edge.id} has unknown target {edge.target}")
        style = ir.connector_styles.get(edge.style_key, "arrow")
        if style not in {"arrow", "line"}:
            issues.append(f"edge style for {edge.id} must be arrow or line")

    return issues


def _node_lookup(ir: DiagramIR) -> dict[str, NodeSpec]:
    return {node.id: node for node in ir.nodes}


def plan_layout(ir: DiagramIR, *, relayout: bool = False) -> LayoutResult:
    layout_cfg = ir.layout
    body_font = int(layout_cfg.get("font_size", 18))
    width = int(layout_cfg.get("canvas_width", 1820))
    height = int(layout_cfg.get("canvas_height", 1380))
    box_rx = float(layout_cfg.get("box_rx", 10))

    left_panel_w = 930.0 if not relayout else 945.0
    left_panel = (70.0, 130.0, left_panel_w, 1110.0)
    panel_gap = _clamp(width * 0.05, 64.0, MAX_INTER_PANEL_GAP)
    right_panel_w = 410.0 if not relayout else 412.0
    right_panel_x = left_panel[0] + left_panel[2] + panel_gap
    right_panel = (right_panel_x, 350.0, right_panel_w, 560.0)

    strategy1 = fit_box("strategy_one", _node_lookup(ir)["strategy_one"].text, 155, 175, 350, 220, body_font + 1)
    strategy2 = fit_box(
        "strategy_two",
        _node_lookup(ir)["strategy_two"].text,
        525 if not relayout else 535,
        175,
        350,
        220,
        body_font,
        min_font_size=max(14, body_font - 2),
    )
    total_x = 375 if not relayout else 370
    total_w = 210 if not relayout else 220
    total_box = fit_box("total_box", _node_lookup(ir)["total_box"].text, total_x, 440, total_w, 145, body_font + 1)
    duplicate_box = fit_box(
        "duplicate_label",
        _node_lookup(ir)["duplicate_label"].text,
        610 if not relayout else 620,
        560 if not relayout else 565,
        330 if not relayout else 338,
        58,
        body_font,
    )
    manual_box = fit_box("manual_box", _node_lookup(ir)["manual_box"].text, 360, 650, 240, 126, body_font + 1)
    excluded_box = fit_box(
        "excluded_box",
        _node_lookup(ir)["excluded_box"].text,
        610 if not relayout else 620,
        640,
        340 if not relayout else 350,
        280 if not relayout else 300,
        body_font,
        min_font_size=max(14, body_font - 3),
    )
    analysis_box = fit_box("analysis_box", _node_lookup(ir)["analysis_box"].text, 375, 1015, 210, 104, body_font + 1)
    citation_box = fit_box(
        "citation_box",
        _node_lookup(ir)["citation_box"].text,
        600 if not relayout else 610,
        1015,
        290 if not relayout else 300,
        90 if not relayout else 98,
        body_font,
        min_font_size=max(14, body_font - 2),
    )

    analysis_boxes: dict[str, Box] = {}
    box_y = 365
    analysis_card_x = right_panel[0] + 55.0
    for idx, step in enumerate(ir.analysis_steps, start=1):
        analysis_boxes[f"analysis_step_{idx}"] = fit_box(
            f"analysis_step_{idx}",
            step,
            analysis_card_x,
            box_y,
            300 if not relayout else 308,
            116 if not relayout else 118,
            body_font,
            min_font_size=max(12, body_font - 3),
        )
        box_y += 136

    boxes = {
        "strategy_one": strategy1,
        "strategy_two": strategy2,
        "total_box": total_box,
        "duplicate_label": duplicate_box,
        "manual_box": manual_box,
        "excluded_box": excluded_box,
        "analysis_box": analysis_box,
        "citation_box": citation_box,
        **analysis_boxes,
    }

    for box in boxes.values():
        fill, stroke = BOX_STYLE_BY_ID.get(box.id, ("#f8fbff", "#5d85d8"))
        box.fill = fill
        box.stroke = stroke
        box.stroke_width = 2.1
        if box.id in {"duplicate_label", "citation_box", "analysis_step_1", "analysis_step_2", "analysis_step_3", "analysis_step_4"}:
            box.rx = 16.0
        else:
            box.rx = max(16.0, box_rx)

    return LayoutResult(
        width=width,
        height=height,
        left_panel=left_panel,
        right_panel=right_panel,
        boxes=boxes,
        analysis_order=list(analysis_boxes.keys()),
        large_arrow_y=690,
        left_caption_y=left_panel[1] + left_panel[3] - 22,
        right_caption_y=1030,
        relayout_applied=relayout,
        relayout_reason="layout_score_below_threshold" if relayout else "",
    )


def assess_layout(layout: LayoutResult, ir: DiagramIR) -> LayoutMetrics:
    boxes = list(layout.boxes.values())
    issues, overlaps = validate_boxes(boxes)
    overlap_safety = check_overlap_safety(layout)
    panel_padding_balance = check_panel_padding_balance(layout)
    alignment_consistency = check_alignment_consistency(layout)
    group_size_normalization = check_group_size_normalization(layout)
    edge_routing_quality = check_edge_routing_quality(layout)
    anchor_consistency = check_anchor_consistency(layout)
    visual_hierarchy = check_visual_hierarchy(layout)
    text_style_consistency = check_text_style_consistency(layout)
    text_containment = check_text_containment(layout)
    semantic_layout_contract = check_semantic_layout_contract(layout)
    inter_panel_gap = check_inter_panel_gap(layout)
    connector_arrow_length = check_connector_arrow_length(layout)
    canvas_utilization = check_canvas_utilization(layout)
    panel_layout_contract = check_panel_layout_contract(layout)
    warnings: list[str] = []
    alignment_deltas = {
        "spine_center_delta": abs(
            (layout.boxes["total_box"].x + layout.boxes["total_box"].w / 2)
            - (layout.boxes["manual_box"].x + layout.boxes["manual_box"].w / 2)
        ),
        "analysis_chain_delta": abs(layout.boxes["analysis_box"].y - layout.boxes["citation_box"].y),
    }
    if alignment_deltas["spine_center_delta"] > 2:
        warnings.append("vertical spine center is slightly misaligned")
    if alignment_deltas["analysis_chain_delta"] > 4:
        warnings.append("bottom row boxes are not aligned tightly enough")

    text_overflows = [issue for issue in issues if issue.startswith("text overflow")]

    score = 100
    score -= len(overlaps) * 25
    score -= len(text_overflows) * 20
    score -= len(overlap_safety["issues"]) * 25
    score -= len(panel_padding_balance["issues"]) * 20
    score -= len(alignment_consistency["row_alignment_errors"]) * 12
    score -= len(alignment_consistency["column_alignment_errors"]) * 12
    score -= len(group_size_normalization["violations"]) * 12
    score -= len(edge_routing_quality["node_crossing_edges"]) * 18
    score -= len(edge_routing_quality["bad_direction_edges"]) * 12
    score -= len(anchor_consistency["violations"]) * 12
    score -= len(semantic_layout_contract["violations"]) * 20
    score -= len(inter_panel_gap["issues"]) * 18
    score -= len(connector_arrow_length["issues"]) * 18
    score -= len(canvas_utilization["issues"]) * 12
    score -= len(panel_layout_contract["violations"]) * 18
    score -= len(text_style_consistency["long_line_nodes"]) * 8
    score -= len(text_style_consistency["orphan_line_nodes"]) * 8
    score -= len(text_style_consistency["font_mismatch_nodes"]) * 8
    score -= len(text_containment["violations"]) * 25
    score -= min(15, int(alignment_deltas["spine_center_delta"] * 2))
    score -= min(10, int(alignment_deltas["analysis_chain_delta"]))
    score = max(0, score)

    if layout.boxes["duplicate_label"].x < layout.boxes["total_box"].x + layout.boxes["total_box"].w + 28:
        warnings.append("duplicate label box is too close to the spine")
        score -= 5
    if layout.boxes["excluded_box"].x < layout.boxes["manual_box"].x + layout.boxes["manual_box"].w + 36:
        warnings.append("excluded box is too close to the spine")
        score -= 5

    readability_passed = (
        score >= 88
        and not overlaps
        and not text_overflows
        and overlap_safety["passed"]
        and panel_padding_balance["passed"]
        and alignment_consistency["passed"]
        and group_size_normalization["passed"]
        and edge_routing_quality["passed"]
        and anchor_consistency["passed"]
        and visual_hierarchy["passed"]
        and text_style_consistency["passed"]
        and text_containment["passed"]
        and semantic_layout_contract["passed"]
        and inter_panel_gap["passed"]
        and connector_arrow_length["passed"]
        and canvas_utilization["passed"]
        and panel_layout_contract["passed"]
    )
    return LayoutMetrics(
        score=max(score, 0),
        issues=issues,
        warnings=warnings,
        overlaps=overlaps,
        overlap_safety=overlap_safety,
        panel_padding_balance=panel_padding_balance,
        alignment_consistency=alignment_consistency,
        group_size_normalization=group_size_normalization,
        edge_routing_quality=edge_routing_quality,
        anchor_consistency=anchor_consistency,
        visual_hierarchy=visual_hierarchy,
        text_style_consistency=text_style_consistency,
        text_containment=text_containment,
        semantic_layout_contract=semantic_layout_contract,
        inter_panel_gap=inter_panel_gap,
        connector_arrow_length=connector_arrow_length,
        canvas_utilization=canvas_utilization,
        panel_layout_contract=panel_layout_contract,
        text_overflows=text_overflows,
        alignment_deltas=alignment_deltas,
        readability_passed=readability_passed,
    )


def maybe_relayout(ir: DiagramIR, first_layout: LayoutResult, first_metrics: LayoutMetrics) -> tuple[LayoutResult, LayoutMetrics]:
    max_passes = int(ir.layout.get("max_relayout_passes", 1))
    if max_passes < 1 or first_metrics.readability_passed:
        return first_layout, first_metrics

    best_layout = first_layout
    best_metrics = first_metrics
    for _ in range(max_passes):
        candidate_layout = plan_layout(ir, relayout=True)
        candidate_metrics = assess_layout(candidate_layout, ir)
        if candidate_metrics.score >= best_metrics.score:
            best_layout = candidate_layout
            best_metrics = candidate_metrics
        if candidate_metrics.readability_passed:
            break
    return best_layout, best_metrics


def _layout_bbox(layout: LayoutResult) -> dict[str, float]:
    min_x = layout.left_panel[0]
    min_y = 60.0
    max_x = layout.right_panel[0] + layout.right_panel[2]
    max_y = max(layout.left_panel[1] + layout.left_panel[3], layout.right_caption_y + 48)

    for box in layout.boxes.values():
        min_x = min(min_x, box.x)
        min_y = min(min_y, box.y)
        max_x = max(max_x, box.x + box.w)
        max_y = max(max_y, box.y + box.h)

    max_x = max(max_x, layout.left_panel[0] + layout.left_panel[2] + 120)
    max_y = max(max_y, layout.large_arrow_y + 32)
    return {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y}


def check_svg_bbox(layout: LayoutResult) -> tuple[bool, dict[str, float], list[str]]:
    bbox = _layout_bbox(layout)
    margin_left = bbox["min_x"]
    margin_top = bbox["min_y"]
    margin_right = layout.width - bbox["max_x"]
    margin_bottom = layout.height - bbox["max_y"]
    issues: list[str] = []

    if margin_left < 24:
        issues.append(f"left margin too small: {margin_left:.1f}")
    if margin_top < 24:
        issues.append(f"top margin too small: {margin_top:.1f}")
    if margin_right < 24:
        issues.append(f"right margin too small: {margin_right:.1f}")
    if margin_bottom < 24:
        issues.append(f"bottom margin too small: {margin_bottom:.1f}")

    bbox.update(
        {
            "margin_left": margin_left,
            "margin_top": margin_top,
            "margin_right": margin_right,
            "margin_bottom": margin_bottom,
        }
    )
    return not issues, bbox, issues


def build_graphviz_json(ir: DiagramIR, layout: LayoutResult) -> dict[str, Any]:
    nodes = []
    for node in ir.nodes:
        box = layout.boxes[node.id]
        nodes.append(
            {
                "name": node.id,
                "kind": node.kind,
                "pos": [round(box.x + box.w / 2, 2), round(box.y + box.h / 2, 2)],
                "width": round(box.w, 2),
                "height": round(box.h, 2),
            }
        )

    edges = []
    for edge in ir.edges:
        source = layout.boxes[edge.source]
        target = layout.boxes[edge.target]
        edges.append(
            {
                "name": edge.id,
                "source": edge.source,
                "target": edge.target,
                "style": ir.connector_styles.get(edge.style_key, "arrow"),
                "points": [
                    [round(source.x + source.w / 2, 2), round(source.y + source.h / 2, 2)],
                    [round(target.x + target.w / 2, 2), round(target.y + target.h / 2, 2)],
                ],
            }
        )

    return {
        "name": "figure1_layout",
        "directed": True,
        "bb": [0, 0, layout.width, layout.height],
        "objects": nodes,
        "edges": edges,
    }


def check_graphviz_json_coords(ir: DiagramIR, layout: LayoutResult) -> tuple[bool, dict[str, Any], list[str]]:
    gv = build_graphviz_json(ir, layout)
    issues: list[str] = []
    node_map = {obj["name"]: obj for obj in gv["objects"]}

    for obj in gv["objects"]:
        x, y = obj["pos"]
        if not (0 <= x <= layout.width and 0 <= y <= layout.height):
            issues.append(f"node out of canvas: {obj['name']}")

    if node_map["strategy_one"]["pos"][0] >= node_map["strategy_two"]["pos"][0]:
        issues.append("strategy nodes are not left-to-right ordered")
    if node_map["total_box"]["pos"][1] >= node_map["manual_box"]["pos"][1]:
        issues.append("vertical spine order total->manual is broken")
    if node_map["manual_box"]["pos"][1] >= node_map["analysis_box"]["pos"][1]:
        issues.append("vertical spine order manual->analysis is broken")
    if node_map["duplicate_label"]["pos"][0] <= node_map["total_box"]["pos"][0]:
        issues.append("duplicate label should be right of total box")
    if node_map["excluded_box"]["pos"][0] <= node_map["manual_box"]["pos"][0]:
        issues.append("excluded box should be right of manual box")

    for analysis_id in layout.analysis_order:
        if node_map[analysis_id]["pos"][0] <= layout.right_panel[0]:
            issues.append(f"{analysis_id} is not fully inside right panel lane")

    return not issues, gv, issues


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_png_rgba(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")

    pos = 8
    width = height = 0
    bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        pos += 4
        chunk_type = data[pos : pos + 4]
        pos += 4
        chunk_data = data[pos : pos + length]
        pos += length + 4
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if bit_depth != 8 or color_type not in {2, 6}:
        raise ValueError(f"unsupported PNG format: bit_depth={bit_depth} color_type={color_type}")

    channels = 4 if color_type == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(width * height * 4)
    prev = [0] * stride
    offset = 0
    out_pos = 0

    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = list(raw[offset : offset + stride])
        offset += stride

        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            up_left = prev[i - channels] if i >= channels else 0
            if filter_type == 1:
                row[i] = (row[i] + left) & 0xFF
            elif filter_type == 2:
                row[i] = (row[i] + up) & 0xFF
            elif filter_type == 3:
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[i] = (row[i] + _paeth_predictor(left, up, up_left)) & 0xFF

        for i in range(0, stride, channels):
            out[out_pos] = row[i]
            out[out_pos + 1] = row[i + 1]
            out[out_pos + 2] = row[i + 2]
            out[out_pos + 3] = row[i + 3] if channels == 4 else 255
            out_pos += 4
        prev = row

    return width, height, bytes(out)


def render_png(svg: str, png_path: Path) -> None:
    subprocess.run(
        ["rsvg-convert", "-o", str(png_path)],
        input=svg.encode("utf-8"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def check_png_edges(svg: str, layout: LayoutResult) -> tuple[bool, dict[str, Any], list[str]]:
    with tempfile.TemporaryDirectory(prefix="figure1_png_check_") as tmpdir:
        png_path = Path(tmpdir) / "check.png"
        render_png(svg, png_path)
        width, height, rgba = _decode_png_rgba(png_path)

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        idx = (y * width + x) * 4
        return rgba[idx], rgba[idx + 1], rgba[idx + 2], rgba[idx + 3]

    def is_ink_like(px: tuple[int, int, int, int]) -> bool:
        r, g, b, a = px
        if a < 24:
            return False
        avg = (r + g + b) / 3
        spread = max(r, g, b) - min(r, g, b)
        return avg < 232 or (avg < 242 and spread > 18)

    edge_depth = 6
    counts = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    samples = {"top": width * edge_depth, "bottom": width * edge_depth, "left": height * edge_depth, "right": height * edge_depth}

    for y in range(edge_depth):
        for x in range(width):
            if is_ink_like(pixel(x, y)):
                counts["top"] += 1
            if is_ink_like(pixel(x, height - 1 - y)):
                counts["bottom"] += 1
    for x in range(edge_depth):
        for y in range(height):
            if is_ink_like(pixel(x, y)):
                counts["left"] += 1
            if is_ink_like(pixel(width - 1 - x, y)):
                counts["right"] += 1

    ratios = {side: counts[side] / max(1, samples[side]) for side in counts}
    issues: list[str] = []
    for side, ratio in ratios.items():
        if ratio > 0.018:
            issues.append(f"png edge content too close on {side}: {ratio:.4f}")

    stats = {
        "width": width,
        "height": height,
        "edge_depth": edge_depth,
        "non_background_counts": counts,
        "non_background_ratios": ratios,
    }
    return not issues, stats, issues


def run_post_render_checks(ir: DiagramIR, layout: LayoutResult, svg: str) -> PostRenderMetrics:
    svg_bbox_passed, svg_bbox, svg_bbox_issues = check_svg_bbox(layout)
    graphviz_json_passed, graphviz_json, graphviz_json_issues = check_graphviz_json_coords(ir, layout)
    png_edge_passed, png_edge_stats, png_edge_issues = check_png_edges(svg, layout)
    return PostRenderMetrics(
        svg_bbox_passed=svg_bbox_passed,
        svg_bbox=svg_bbox,
        svg_bbox_issues=svg_bbox_issues,
        graphviz_json_passed=graphviz_json_passed,
        graphviz_json=graphviz_json,
        graphviz_json_issues=graphviz_json_issues,
        png_edge_passed=png_edge_passed,
        png_edge_stats=png_edge_stats,
        png_edge_issues=png_edge_issues,
    )


def post_render_passed(metrics: PostRenderMetrics) -> bool:
    return metrics.svg_bbox_passed and metrics.graphviz_json_passed and metrics.png_edge_passed


def render_svg(ir: DiagramIR, layout: LayoutResult) -> str:
    title_font = int(ir.layout.get("title_font_size", 34))
    caption_font = int(ir.layout.get("caption_font_size", 23))
    stage_font = int(ir.layout.get("stage_font_size", 26))
    panel_rx = float(ir.layout.get("panel_rx", 18))
    stage_pill_rx = float(ir.layout.get("stage_pill_rx", 18))
    connector_styles = ir.connector_styles
    boxes = layout.boxes

    bg = """
<defs>
  <radialGradient id="bgGlow" cx="20%" cy="15%" r="110%">
    <stop offset="0%" stop-color="#ffffff"/>
    <stop offset="48%" stop-color="#f8fbff"/>
    <stop offset="100%" stop-color="#eef4fb"/>
  </radialGradient>
  <radialGradient id="cornerGlow" cx="0%" cy="0%" r="90%">
    <stop offset="0%" stop-color="#dbeafe" stop-opacity="0.55"/>
    <stop offset="55%" stop-color="#f8fbff" stop-opacity="0.18"/>
    <stop offset="100%" stop-color="#f8fbff" stop-opacity="0"/>
  </radialGradient>
</defs>
<rect width="100%" height="100%" fill="url(#bgGlow)"/>
<circle cx="100" cy="90" r="240" fill="url(#cornerGlow)"/>
"""

    def connector(edge_id: str, points: list[tuple[float, float]], *, stroke_width: float = 2.3) -> str:
        style = connector_styles.get(edge_id, "arrow")
        if style == "line":
            return draw_polyline(points, stroke_width=stroke_width) if len(points) > 2 else draw_line(*points[0], *points[1], stroke_width=stroke_width)
        return draw_arrow_polyline(points, stroke_width=stroke_width)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" height="{layout.height}" '
        f'viewBox="0 0 {layout.width} {layout.height}">',
        bg,
        draw_multiline_text(
            layout.width / 2,
            75,
            760,
            ir.title,
            font_size=title_font,
            font_weight="700",
            fill="#1f2e4f",
            italic=True,
        ),
        draw_panel(*layout.left_panel, title=ir.left_caption, font_size=caption_font, rx=panel_rx),
        draw_panel(*layout.right_panel, rx=panel_rx),
        draw_label_pill(*STAGE_PILLS["identification"], ir.stage_labels[0], stage_font, stage_pill_rx),
        draw_label_pill(*STAGE_PILLS["screening"], ir.stage_labels[1], stage_font, stage_pill_rx),
        draw_label_pill(*STAGE_PILLS["included"], ir.stage_labels[2], stage_font, stage_pill_rx),
    ]

    ordered_box_ids = [
        "strategy_one",
        "strategy_two",
        "total_box",
        "duplicate_label",
        "manual_box",
        "excluded_box",
        "analysis_box",
        "citation_box",
        *layout.analysis_order,
    ]
    for box_id in ordered_box_ids:
        parts.append(draw_box(boxes[box_id], shadow=True))

    total = boxes["total_box"]
    manual = boxes["manual_box"]
    analysis = boxes["analysis_box"]
    citation = boxes["citation_box"]
    strategy1 = boxes["strategy_one"]
    strategy2 = boxes["strategy_two"]
    duplicate = boxes["duplicate_label"]
    excluded = boxes["excluded_box"]
    big_arrow_tail_x, big_arrow_tip_x = _big_arrow_bounds(layout)

    shared_merge_y = total.y - 28
    duplicate_branch_y = duplicate.y + duplicate.h / 2
    excluded_branch_y = manual.y + manual.h + 36
    parts.extend(
        [
            connector(
                "strategy_one_to_total",
                [
                    (strategy1.x + strategy1.w / 2, strategy1.y + strategy1.h),
                    (strategy1.x + strategy1.w / 2, shared_merge_y),
                    (total.x + total.w / 2, shared_merge_y),
                    (total.x + total.w / 2, total.y),
                ],
            ),
            connector(
                "strategy_two_to_total",
                [
                    (strategy2.x + strategy2.w / 2, strategy2.y + strategy2.h),
                    (strategy2.x + strategy2.w / 2, shared_merge_y),
                    (total.x + total.w / 2, shared_merge_y),
                    (total.x + total.w / 2, total.y),
                ],
            ),
            connector(
                "total_to_manual",
                [
                    (total.x + total.w / 2, total.y + total.h),
                    (total.x + total.w / 2, manual.y),
                ],
            ),
            connector(
                "total_to_duplicate",
                [
                    (total.x + total.w / 2, duplicate_branch_y),
                    (duplicate.x, duplicate_branch_y),
                ],
            ),
            connector(
                "manual_to_excluded",
                [
                    (manual.x + manual.w / 2, excluded_branch_y),
                    (excluded.x, excluded_branch_y),
                ],
            ),
            connector(
                "manual_to_analysis",
                [
                    (manual.x + manual.w / 2, manual.y + manual.h),
                    (manual.x + manual.w / 2, analysis.y),
                ],
            ),
            connector(
                "analysis_to_citation",
                [
                    (analysis.x + analysis.w, analysis.y + analysis.h / 2),
                    (citation.x, analysis.y + analysis.h / 2),
                ],
            ),
            (
                draw_large_arrow(big_arrow_tail_x, layout.large_arrow_y, big_arrow_tip_x)
                if connector_styles.get("analysis_panel_arrow", "arrow") != "line"
                else draw_line(big_arrow_tail_x, layout.large_arrow_y, big_arrow_tip_x, layout.large_arrow_y, stroke_width=3.2)
            ),
            draw_multiline_text(
                layout.right_panel[0] + layout.right_panel[2] / 2,
                layout.right_caption_y,
                layout.right_panel[2] - 20,
                ir.right_caption,
                font_size=caption_font,
                font_weight="700",
                fill="#233353",
                italic=True,
            ),
        ]
    )

    return "".join(parts) + "</svg>\n"


def run_pipeline(spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ir = build_ir(spec)
    logic_issues = validate_ir(ir)
    if logic_issues:
        raise ValueError("logic validation failed: " + "; ".join(logic_issues))

    first_layout = plan_layout(ir, relayout=False)
    first_metrics = assess_layout(first_layout, ir)
    first_svg = render_svg(ir, first_layout)
    first_post = run_post_render_checks(ir, first_layout, first_svg)

    final_layout = first_layout
    final_metrics = first_metrics
    final_svg = first_svg
    final_post = first_post

    if not first_metrics.readability_passed or not post_render_passed(first_post):
        final_layout, final_metrics = maybe_relayout(ir, first_layout, first_metrics)
        if not first_metrics.readability_passed and not post_render_passed(first_post):
            final_layout.relayout_reason = "layout_and_post_render_checks_failed"
        elif not first_metrics.readability_passed:
            final_layout.relayout_reason = "layout_score_below_threshold"
        else:
            final_layout.relayout_reason = "post_render_checks_failed"
        final_svg = render_svg(ir, final_layout)
        final_post = run_post_render_checks(ir, final_layout, final_svg)

    if not final_metrics.readability_passed:
        raise ValueError(
            "readability check failed: "
            + "; ".join(
                final_metrics.issues
                + final_metrics.overlap_safety.get("issues", [])
                + final_metrics.panel_padding_balance.get("issues", [])
                + final_metrics.alignment_consistency.get("row_alignment_errors", [])
                + final_metrics.alignment_consistency.get("column_alignment_errors", [])
                + final_metrics.group_size_normalization.get("violations", [])
                + final_metrics.edge_routing_quality.get("node_crossing_edges", [])
                + final_metrics.edge_routing_quality.get("bad_direction_edges", [])
                + final_metrics.anchor_consistency.get("violations", [])
                + final_metrics.visual_hierarchy.get("warnings", [])
                + final_metrics.text_style_consistency.get("long_line_nodes", [])
                + final_metrics.text_style_consistency.get("orphan_line_nodes", [])
                + final_metrics.text_style_consistency.get("font_mismatch_nodes", [])
                + final_metrics.text_containment.get("violations", [])
                + final_metrics.semantic_layout_contract.get("violations", [])
                + final_metrics.inter_panel_gap.get("issues", [])
                + final_metrics.connector_arrow_length.get("issues", [])
                + final_metrics.canvas_utilization.get("issues", [])
                + final_metrics.panel_layout_contract.get("violations", [])
                + final_metrics.warnings
            )
        )
    if not post_render_passed(final_post):
        raise ValueError(
            "post-render checks failed: "
            + "; ".join(
                final_post.svg_bbox_issues
                + final_post.graphviz_json_issues
                + final_post.png_edge_issues
            )
        )

    report = {
        "pipeline": [
            "graph_ir",
            "logic_validation",
            "initial_render",
            "layout_quality_assessment",
            "overlap_safety_check",
            "left_panel_padding_balance_check",
            "alignment_consistency_check",
            "group_size_normalization_check",
            "edge_routing_quality_check",
            "anchor_consistency_check",
            "visual_hierarchy_check",
            "text_style_consistency_check",
            "measured_text_containment_check",
            "semantic_layout_contract_check",
            "inter_panel_gap_check",
            "connector_arrow_length_check",
            "canvas_utilization_check",
            "panel_layout_contract_check",
            "svg_bbox_check",
            "graphviz_json_coordinate_check",
            "png_edge_pixel_check",
            "auto_relayout_or_constraints",
            "rerender",
            "human_readability_check",
            "final_output",
        ],
        "logic_validation": {"passed": True, "issues": logic_issues},
        "initial_layout": asdict(first_metrics),
        "initial_post_render": asdict(first_post),
        "final_layout": asdict(final_metrics),
        "final_style": {
            "visual_hierarchy": final_metrics.visual_hierarchy,
            "text_style_consistency": final_metrics.text_style_consistency,
            "color_semantics": final_metrics.visual_hierarchy.get("color_semantics", {}),
        },
        "final_post_render": asdict(final_post),
        "relayout_applied": final_layout.relayout_applied,
        "relayout_reason": final_layout.relayout_reason,
        "validation": {
            "logic_validation_passed": True,
            "readability_passed": final_metrics.readability_passed,
            "measured_text_containment_passed": final_metrics.text_containment["passed"],
            "svg_bbox_passed": final_post.svg_bbox_passed,
            "graphviz_json_passed": final_post.graphviz_json_passed,
            "png_edge_passed": final_post.png_edge_passed,
            "passed": final_metrics.readability_passed and post_render_passed(final_post),
        },
        "graph_ir": {
            "title": ir.title,
            "stage_labels": ir.stage_labels,
            "node_count": len(ir.nodes),
            "edge_count": len(ir.edges),
            "nodes": [asdict(node) for node in ir.nodes],
            "edges": [asdict(edge) for edge in ir.edges],
        },
    }
    return final_svg, report


def load_spec(path: Path | None) -> dict[str, Any]:
    if path is None:
        return json.loads(json.dumps(DEFAULT_SPEC))
    data = json.loads(path.read_text(encoding="utf-8"))
    merged = json.loads(json.dumps(DEFAULT_SPEC))
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Render review Figure 1 style diagram from JSON spec.")
    parser.add_argument("--spec", type=Path, help="JSON spec path. If omitted, the built-in template is used.")
    parser.add_argument("--output", "-o", type=Path, required=False, help="Output SVG path.")
    parser.add_argument("--dump-template", action="store_true", help="Print the default JSON template and exit.")
    parser.add_argument("--validate-only", action="store_true", help="Run the full pipeline but do not write SVG.")
    parser.add_argument("--dump-ir", action="store_true", help="Print the graph IR as JSON and exit.")
    parser.add_argument("--report", type=Path, help="Optional JSON report path for pipeline results.")
    args = parser.parse_args()

    if args.dump_template:
        print(json.dumps(DEFAULT_SPEC, ensure_ascii=False, indent=2))
        return 0

    spec = load_spec(args.spec)

    if args.dump_ir:
        print(json.dumps(asdict(build_ir(spec)), ensure_ascii=False, indent=2))
        return 0

    svg, report = run_pipeline(spec)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.validate_only:
        print("VALID=ok")
        return 0

    if not args.output:
        raise SystemExit("--output is required unless --dump-template, --dump-ir, or --validate-only is used.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"OUTPUT={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
