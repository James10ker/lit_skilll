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
    max_units = max(5.0, width_px / (font_size * 0.92))
    wrapped: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            wrapped.append("")
            continue
        if " " in line:
            wrapped.extend(_wrap_line(line, max_units))
        else:
            wrapped.extend(_wrap_hard(line, max_units))
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
        f'height="{box.h:.1f}" rx="{box.rx:.1f}" fill="#dfe8fb" opacity="0.45"/>'
    )
    rect = (
        f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
        f'rx="{box.rx:.1f}" fill="{box.fill}" stroke="{box.stroke}" '
        f'stroke-width="{box.stroke_width:.1f}"/>'
    )
    text = draw_multiline_text(
        box.x + box.w / 2,
        box.y + box.h / 2,
        box.w - 36,
        box.text,
        font_size=box.font_size,
    )
    return (shadow_el if shadow else "") + rect + text


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


def draw_line(x1: float, y1: float, x2: float, y2: float, stroke_width: float = 2.6) -> str:
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="#7ba4e2" stroke-width="{stroke_width:.1f}" stroke-linecap="round"/>'
    )


def draw_polyline(points: list[tuple[float, float]], stroke_width: float = 2.6) -> str:
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (
        f'<polyline points="{serialized}" fill="none" '
        f'stroke="#7ba4e2" stroke-width="{stroke_width:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
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
        f'{right[0]:.1f},{right[1]:.1f}" fill="#7ba4e2"/>'
    )


def draw_arrow_polyline(points: list[tuple[float, float]], stroke_width: float = 2.8) -> str:
    if len(points) < 2:
        return ""
    serialized = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    (x1, y1), (x2, y2) = points[-2], points[-1]
    return (
        f'<polyline points="{serialized}" fill="none" '
        f'stroke="#7ba4e2" stroke-width="{stroke_width:.1f}" '
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
        lines = wrap_text(text, w - 36, size)
        if text_height(lines, size) <= h - BODY_TEXT_PAD_Y:
            chosen = size
            break
        chosen = size
    return Box(x=x, y=y, w=w, h=h, text=text, font_size=chosen, id=node_id)


def validate_boxes(boxes: list[Box]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    overlaps: list[str] = []
    for box in boxes:
        lines = wrap_text(box.text, box.w - 36, box.font_size)
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

    left_panel = (70.0, 130.0, 1130.0 if not relayout else 1145.0, 1110.0)
    right_panel = (1290.0 if not relayout else 1298.0, 350.0, 410.0 if not relayout else 412.0, 560.0)

    strategy1 = fit_box("strategy_one", _node_lookup(ir)["strategy_one"].text, 125, 180, 260, 205, body_font + 1)
    strategy2 = fit_box(
        "strategy_two",
        _node_lookup(ir)["strategy_two"].text,
        410 if not relayout else 420,
        175,
        350 if not relayout else 360,
        220 if not relayout else 228,
        body_font,
        min_font_size=max(14, body_font - 2),
    )
    total_x = 345 if not relayout else 340
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
    manual_box = fit_box("manual_box", _node_lookup(ir)["manual_box"].text, 330, 650, 240, 126, body_font + 1)
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
    analysis_box = fit_box("analysis_box", _node_lookup(ir)["analysis_box"].text, 355, 1015, 190, 104, body_font + 1)
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
    box_y = 390
    for idx, step in enumerate(ir.analysis_steps, start=1):
        analysis_boxes[f"analysis_step_{idx}"] = fit_box(
            f"analysis_step_{idx}",
            step,
            1345 if not relayout else 1350,
            box_y,
            300 if not relayout else 308,
            96 if not relayout else 102,
            body_font,
        )
        box_y += 116 if not relayout else 120

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
        if box.id in {"duplicate_label", "citation_box", "analysis_step_1", "analysis_step_2", "analysis_step_3", "analysis_step_4"}:
            box.rx = 2.0
        else:
            box.rx = box_rx

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
    score -= min(15, int(alignment_deltas["spine_center_delta"] * 2))
    score -= min(10, int(alignment_deltas["analysis_chain_delta"]))
    score = max(0, score)

    if layout.boxes["duplicate_label"].x < layout.boxes["total_box"].x + layout.boxes["total_box"].w + 28:
        warnings.append("duplicate label box is too close to the spine")
        score -= 5
    if layout.boxes["excluded_box"].x < layout.boxes["manual_box"].x + layout.boxes["manual_box"].w + 36:
        warnings.append("excluded box is too close to the spine")
        score -= 5

    readability_passed = score >= 88 and not overlaps and not text_overflows
    return LayoutMetrics(
        score=max(score, 0),
        issues=issues,
        warnings=warnings,
        overlaps=overlaps,
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
    <stop offset="0%" stop-color="#fff8ec"/>
    <stop offset="38%" stop-color="#f8fbff"/>
    <stop offset="100%" stop-color="#eef5ff"/>
  </radialGradient>
  <radialGradient id="cornerGlow" cx="0%" cy="0%" r="90%">
    <stop offset="0%" stop-color="#ffe9c8" stop-opacity="0.85"/>
    <stop offset="55%" stop-color="#f8fbff" stop-opacity="0.20"/>
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
        draw_label_pill(95, 275, 42, 170, ir.stage_labels[0], stage_font, stage_pill_rx),
        draw_label_pill(95, 605, 42, 150, ir.stage_labels[1], stage_font, stage_pill_rx),
        draw_label_pill(95, 955, 42, 145, ir.stage_labels[2], stage_font, stage_pill_rx),
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
        parts.append(draw_box(boxes[box_id], shadow=False))

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
                draw_large_arrow(layout.left_panel[0] + layout.left_panel[2] + 6, layout.large_arrow_y, layout.right_panel[0] - 18)
                if connector_styles.get("analysis_panel_arrow", "arrow") != "line"
                else draw_line(layout.left_panel[0] + layout.left_panel[2], layout.large_arrow_y, layout.right_panel[0] - 24, layout.large_arrow_y, stroke_width=3.2)
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
            + "; ".join(final_metrics.issues + final_metrics.warnings)
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
        "final_post_render": asdict(final_post),
        "relayout_applied": final_layout.relayout_applied,
        "relayout_reason": final_layout.relayout_reason,
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
