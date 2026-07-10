#!/usr/bin/env python3
"""Render a bibliometric heterogeneous connection graph from scraped records.

The visual language is inspired by bibliometric collaboration figures: white
background, colored circular nodes, bold labels, and many semi-transparent
curved links. It intentionally synthesizes a same-purpose graph from the current
record set instead of extracting or copying a reference article's figure.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


NODE_TYPES = ("author", "journal", "year", "topic", "affiliation")
TYPE_LABELS = {
    "author": "Authors",
    "journal": "Journals",
    "year": "Years",
    "topic": "Topics",
    "affiliation": "Affiliations",
}
TYPE_COLORS = {
    "author": "#12bfe8",
    "journal": "#f28c28",
    "year": "#8b5cf6",
    "topic": "#5fbf00",
    "affiliation": "#c765d9",
}
TYPE_RADII = {
    "topic": 0.30,
    "author": 0.43,
    "journal": 0.55,
    "affiliation": 0.65,
    "year": 0.75,
}
EDGE_RULES = {
    ("author", "author"),
    ("author", "affiliation"),
    ("author", "journal"),
    ("author", "topic"),
    ("author", "year"),
    ("journal", "year"),
    ("topic", "year"),
    ("affiliation", "topic"),
}
DEFAULT_WIDTH = 1600
DEFAULT_HEIGHT = 1120
DEFAULT_SEED = 20260710
SAMPLE_RECORDS = {
    "records": [
        {
            "title": "Intelligent tutoring systems for adaptive learning",
            "authors": ["Smith, J.", "Chen, L.", "Garcia, M."],
            "journal": "Computers & Education",
            "year": 2019,
            "topics": ["Intelligent tutoring systems", "Adaptive learning"],
            "affiliations": ["Arizona State University", "Tsinghua University"],
            "citations": 184,
        },
        {
            "title": "Educational data mining for learner prediction",
            "authors": ["Chen, L.", "Kumar, R.", "Wilson, A."],
            "journal": "IEEE Transactions on Learning Technologies",
            "year": 2020,
            "topics": ["Educational data mining", "Learner prediction"],
            "affiliations": ["Tsinghua University", "Carnegie Mellon University"],
            "citations": 231,
        },
        {
            "title": "Affective computing in online learning",
            "authors": ["Garcia, M.", "Nakamura, H."],
            "journal": "Educational Technology & Society",
            "year": 2021,
            "topics": ["Affective computing", "Online learning"],
            "affiliations": ["University of Tokyo", "Arizona State University"],
            "citations": 96,
        },
        {
            "title": "Recommender systems for personalized learning paths",
            "authors": ["Wilson, A.", "Brown, S.", "Smith, J."],
            "journal": "British Journal of Educational Technology",
            "year": 2022,
            "topics": ["Recommender systems", "Personalized learning"],
            "affiliations": ["Carnegie Mellon University", "University of Edinburgh"],
            "citations": 143,
        },
        {
            "title": "Knowledge tracing with neural networks",
            "authors": ["Kumar, R.", "Nakamura, H.", "Li, Y."],
            "journal": "Computers & Education",
            "year": 2023,
            "topics": ["Knowledge tracing", "Neural networks"],
            "affiliations": ["Carnegie Mellon University", "University of Tokyo"],
            "citations": 117,
        },
        {
            "title": "Natural language processing for writing feedback",
            "authors": ["Li, Y.", "Brown, S.", "Chen, L."],
            "journal": "International Journal of Artificial Intelligence in Education",
            "year": 2024,
            "topics": ["Natural language processing", "Writing feedback"],
            "affiliations": ["Tsinghua University", "University of Edinburgh"],
            "citations": 72,
        },
    ]
}


@dataclass
class PaperRecord:
    title: str
    authors: list[str]
    journal: str
    year: str
    topics: list[str]
    affiliations: list[str]
    citations: float


@dataclass
class Node:
    id: str
    label: str
    type: str
    citations: float = 0.0
    papers: set[str] = field(default_factory=set)
    occurrences: int = 0
    x: float = 0.0
    y: float = 0.0
    r: float = 8.0


@dataclass
class Edge:
    source: str
    target: str
    weight: float = 0.0
    citations: float = 0.0
    papers: set[str] = field(default_factory=set)


@dataclass
class LabelBox:
    node_id: str
    lines: tuple[str, ...]
    x: float
    y: float
    w: float
    h: float
    anchor: str
    font_size: float


def stable_hash(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def split_multi(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        text = str(value).strip()
        if not text:
            return []
        delimiter = ";"
        for candidate in (";", "|", "\n"):
            if candidate in text:
                delimiter = candidate
                break
        raw = text.split(delimiter)
    items = []
    seen = set()
    for item in raw:
        label = str(item).strip()
        if is_named_label(label) and label.lower() not in seen:
            seen.add(label.lower())
            items.append(label)
    return items


def clean_scalar(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def is_named_label(value: str) -> bool:
    """Reject empty and placeholder metadata so every rendered node is meaningful."""
    return value.strip().lower() not in {"", "-", "--", "n/a", "na", "none", "null", "unknown", "unknown source", "unknown year"}


def parse_citations(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return max(0.0, float(str(value).replace(",", "").strip()))
    except ValueError:
        return 0.0


def normalize_record(raw: dict[str, Any], index: int) -> PaperRecord:
    title = clean_scalar(raw.get("title") or raw.get("paper_title"), f"record-{index + 1}")
    authors = split_multi(raw.get("authors") or raw.get("author"))
    journal = clean_scalar(raw.get("journal") or raw.get("source") or raw.get("publication_source"))
    year = clean_scalar(raw.get("year") or raw.get("publication_year"))
    topics = split_multi(raw.get("topics") or raw.get("keywords") or raw.get("theme"))
    affiliations = split_multi(raw.get("affiliations") or raw.get("institutions") or raw.get("author_units"))
    citations = parse_citations(raw.get("citations") or raw.get("citation_count") or raw.get("cited_by"))
    return PaperRecord(
        title=title,
        authors=authors,
        journal=journal,
        year=year,
        topics=topics,
        affiliations=affiliations,
        citations=citations,
    )


def load_records(path: Path | None) -> list[PaperRecord]:
    if path is None:
        data: Any = SAMPLE_RECORDS
    elif path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            data = {"records": list(csv.DictReader(handle))}
    else:
        data = json.loads(path.read_text(encoding="utf-8"))

    raw_records = data.get("records", data) if isinstance(data, dict) else data
    if not isinstance(raw_records, list):
        raise ValueError("input must be a JSON list, a JSON object with records, or a CSV file")
    records = [normalize_record(raw, idx) for idx, raw in enumerate(raw_records) if isinstance(raw, dict)]
    if not records:
        raise ValueError("no usable records found")
    return records


def node_id(node_type: str, label: str) -> str:
    return f"{node_type}:{label.strip().lower()}"


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def add_node(nodes: dict[str, Node], node_type: str, label: str, record: PaperRecord) -> str:
    nid = node_id(node_type, label)
    if nid not in nodes:
        nodes[nid] = Node(id=nid, label=label, type=node_type)
    node = nodes[nid]
    node.occurrences += 1
    node.citations += record.citations
    node.papers.add(record.title)
    return nid


def build_graph(records: list[PaperRecord]) -> tuple[dict[str, Node], dict[tuple[str, str], Edge], list[str]]:
    nodes: dict[str, Node] = {}
    edges: dict[tuple[str, str], Edge] = {}
    warnings: list[str] = []

    for record in records:
        groups = {
            "author": record.authors,
            "journal": [record.journal] if is_named_label(record.journal) else [],
            "year": [record.year] if is_named_label(record.year) else [],
            "topic": record.topics,
            "affiliation": record.affiliations,
        }
        if not record.authors:
            warnings.append(f"{record.title}: missing authors")
        if not record.topics:
            warnings.append(f"{record.title}: missing topics")
        if not record.affiliations:
            warnings.append(f"{record.title}: missing affiliations")

        record_nodes: dict[str, list[str]] = {}
        for node_type, labels in groups.items():
            record_nodes[node_type] = [
                add_node(nodes, node_type, label, record)
                for label in labels
                if is_named_label(label)
            ]

        for left_type, left_ids in record_nodes.items():
            for right_type, right_ids in record_nodes.items():
                if left_type > right_type:
                    continue
                if (left_type, right_type) not in EDGE_RULES and (right_type, left_type) not in EDGE_RULES:
                    continue
                for left_id in left_ids:
                    for right_id in right_ids:
                        if left_id == right_id:
                            continue
                        key = pair_key(left_id, right_id)
                        if key not in edges:
                            edges[key] = Edge(source=key[0], target=key[1])
                        edge = edges[key]
                        edge.weight += 1.0
                        edge.citations += record.citations
                        edge.papers.add(record.title)

    return nodes, edges, warnings


def filter_graph(
    nodes: dict[str, Node],
    edges: dict[tuple[str, str], Edge],
    max_nodes_per_type: int,
    min_node_citations: float,
) -> tuple[dict[str, Node], dict[tuple[str, str], Edge]]:
    kept: dict[str, Node] = {}
    by_type: dict[str, list[Node]] = defaultdict(list)
    for node in nodes.values():
        by_type[node.type].append(node)
    for node_type in NODE_TYPES:
        ranked = sorted(by_type[node_type], key=lambda n: (n.citations, n.occurrences, n.label.lower()), reverse=True)
        for node in ranked[:max_nodes_per_type]:
            if node.citations >= min_node_citations:
                kept[node.id] = node
    kept_edges = {
        key: edge
        for key, edge in edges.items()
        if edge.source in kept and edge.target in kept
    }
    return kept, kept_edges


def scale(value: float, low: float, high: float, out_low: float, out_high: float) -> float:
    if high <= low:
        return (out_low + out_high) / 2
    t = (value - low) / (high - low)
    return out_low + max(0.0, min(1.0, t)) * (out_high - out_low)


def assign_initial_positions(nodes: dict[str, Node], seed: int) -> None:
    rng = random.Random(seed)
    by_type: dict[str, list[Node]] = defaultdict(list)
    for node in nodes.values():
        by_type[node.type].append(node)
    for node_type, typed_nodes in by_type.items():
        typed_nodes.sort(key=lambda n: (-n.citations, n.label.lower()))
        step = (2 * math.pi) / max(1, len(typed_nodes))
        offset = (stable_hash(node_type) % 360) * math.pi / 180
        radius = TYPE_RADII.get(node_type, 0.5)
        for idx, node in enumerate(typed_nodes):
            jitter = rng.uniform(-0.10, 0.10)
            angle = offset + idx * step + jitter
            node.x = radius * math.cos(angle)
            node.y = radius * math.sin(angle)


def layout_graph(nodes: dict[str, Node], edges: dict[tuple[str, str], Edge], seed: int, iterations: int = 260) -> None:
    if not nodes:
        return
    assign_initial_positions(nodes, seed)
    node_list = list(nodes.values())
    max_weight = max((edge.weight for edge in edges.values()), default=1.0)

    for iteration in range(iterations):
        cooling = 1.0 - (iteration / max(1, iterations))
        disp = {node.id: [0.0, 0.0] for node in node_list}

        for i, left in enumerate(node_list):
            for right in node_list[i + 1 :]:
                dx = left.x - right.x
                dy = left.y - right.y
                dist_sq = dx * dx + dy * dy + 0.002
                force = 0.0035 / dist_sq
                disp[left.id][0] += dx * force
                disp[left.id][1] += dy * force
                disp[right.id][0] -= dx * force
                disp[right.id][1] -= dy * force

        for edge in edges.values():
            source = nodes[edge.source]
            target = nodes[edge.target]
            dx = target.x - source.x
            dy = target.y - source.y
            dist = math.sqrt(dx * dx + dy * dy) + 0.001
            desired = 0.36 if source.type != target.type else 0.25
            force = (dist - desired) * (0.008 + 0.016 * edge.weight / max_weight)
            fx = dx / dist * force
            fy = dy / dist * force
            disp[source.id][0] += fx
            disp[source.id][1] += fy
            disp[target.id][0] -= fx
            disp[target.id][1] -= fy

        for node in node_list:
            type_radius = TYPE_RADII.get(node.type, 0.55)
            current_radius = math.sqrt(node.x * node.x + node.y * node.y) + 0.001
            radial_force = (type_radius - current_radius) * 0.012
            disp[node.id][0] += node.x / current_radius * radial_force
            disp[node.id][1] += node.y / current_radius * radial_force

            step = min(0.045, math.sqrt(disp[node.id][0] ** 2 + disp[node.id][1] ** 2)) * cooling
            if step > 0:
                angle = math.atan2(disp[node.id][1], disp[node.id][0])
                node.x += math.cos(angle) * step
                node.y += math.sin(angle) * step
            radius = math.sqrt(node.x * node.x + node.y * node.y)
            if radius > 0.94:
                node.x *= 0.94 / radius
                node.y *= 0.94 / radius


def normalize_to_canvas(nodes: dict[str, Node], width: int, height: int) -> None:
    if not nodes:
        return
    min_x = min(node.x for node in nodes.values())
    max_x = max(node.x for node in nodes.values())
    min_y = min(node.y for node in nodes.values())
    max_y = max(node.y for node in nodes.values())
    span_x = max(max_x - min_x, 0.1)
    span_y = max(max_y - min_y, 0.1)
    margin_x = width * 0.11
    margin_y = height * 0.15
    for node in nodes.values():
        node.x = margin_x + (node.x - min_x) / span_x * (width - 2 * margin_x)
        node.y = margin_y + (node.y - min_y) / span_y * (height - 2 * margin_y)


def assign_node_sizes(nodes: dict[str, Node]) -> None:
    values = [math.log1p(node.citations) for node in nodes.values()]
    low = min(values, default=0.0)
    high = max(values, default=1.0)
    for node in nodes.values():
        node.r = scale(math.log1p(node.citations), low, high, 7.0, 42.0)
        if node.type == "year":
            node.r *= 0.82


def wrap_label(label: str, *, max_chars: int = 14, max_lines: int = 3) -> tuple[str, ...]:
    """Create a compact, deterministic label that can fit inside a circular node."""
    text = display_label(label)
    words = text.split()
    if len(words) <= 1:
        return tuple(text[index : index + max_chars] for index in range(0, len(text), max_chars))[:max_lines]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) <= max_lines:
        return tuple(lines)
    shortened = list(lines[:max_lines])
    shortened[-1] = shortened[-1][: max(1, max_chars - 3)].rstrip() + "..."
    return tuple(shortened)


def label_font_size(node: Node) -> float:
    # A stable size keeps the measured label footprint identical to the final SVG.
    del node
    return 10.0


def label_dimensions(lines: tuple[str, ...], font_size: float) -> tuple[float, float]:
    return max(estimate_label_width(line, font_size) for line in lines), len(lines) * font_size * 1.18


def expand_nodes_for_labels(nodes: dict[str, Node]) -> None:
    """Keep every label inside its own node, leaving a small readable margin."""
    for node in nodes.values():
        lines = wrap_label(node.label)
        font_size = label_font_size(node)
        text_w, text_h = label_dimensions(lines, font_size)
        required_radius = math.hypot(text_w / 2.0, text_h / 2.0) + 7.0
        node.r = max(node.r, required_radius)


def clamp_node_to_canvas(node: Node, width: int, height: int) -> None:
    margin_top = 86.0
    margin_bottom = 72.0
    node.x = max(node.r + 8.0, min(width - node.r - 8.0, node.x))
    node.y = max(margin_top + node.r, min(height - margin_bottom - node.r, node.y))


def resolve_node_overlaps(nodes: dict[str, Node], width: int, height: int, iterations: int = 180) -> None:
    node_list = list(nodes.values())
    for _ in range(iterations):
        moved = False
        for i, left in enumerate(node_list):
            for right in node_list[i + 1 :]:
                dx = right.x - left.x
                dy = right.y - left.y
                dist = math.sqrt(dx * dx + dy * dy)
                min_dist = left.r + right.r + 5.0
                if dist >= min_dist:
                    continue
                if dist < 0.001:
                    angle = (stable_hash(left.id + right.id) % 360) * math.pi / 180
                    dx = math.cos(angle)
                    dy = math.sin(angle)
                    dist = 1.0
                push = (min_dist - dist) / 2.0
                ux = dx / dist
                uy = dy / dist
                left.x -= ux * push
                left.y -= uy * push
                right.x += ux * push
                right.y += uy * push
                clamp_node_to_canvas(left, width, height)
                clamp_node_to_canvas(right, width, height)
                moved = True
        if not moved:
            break


def edge_width(edge: Edge, max_citations: float) -> float:
    return scale(math.log1p(edge.citations), 0.0, math.log1p(max_citations), 0.35, 7.5)


def display_label(label: str) -> str:
    if len(label) > 42:
        return label[:39].rstrip() + "..."
    return label


def estimate_label_width(text: str, font_size: float) -> float:
    units = 0.0
    for char in text:
        if ord(char) > 127:
            units += 0.95
        elif char in "il.,:;|'":
            units += 0.28
        elif char in "MW@#%&":
            units += 0.86
        elif char == " ":
            units += 0.34
        else:
            units += 0.56
    return max(font_size * 1.8, units * font_size)


def rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    pad: float = 0.0,
) -> bool:
    return not (
        a[2] + pad <= b[0]
        or b[2] + pad <= a[0]
        or a[3] + pad <= b[1]
        or b[3] + pad <= a[1]
    )


def label_rect(label: LabelBox) -> tuple[float, float, float, float]:
    return (
        label.x - label.w / 2,
        label.y - label.h / 2,
        label.x + label.w / 2,
        label.y + label.h / 2,
    )


def circle_rect(node: Node, pad: float = 0.0) -> tuple[float, float, float, float]:
    return node.x - node.r - pad, node.y - node.r - pad, node.x + node.r + pad, node.y + node.r + pad


def rect_overlaps_circle(rect: tuple[float, float, float, float], node: Node, pad: float = 0.0) -> bool:
    """Return whether an axis-aligned text box intersects a circular node."""
    closest_x = max(rect[0], min(node.x, rect[2]))
    closest_y = max(rect[1], min(node.y, rect[3]))
    return math.hypot(node.x - closest_x, node.y - closest_y) < node.r + pad


def place_labels(nodes: dict[str, Node], *, width: int, height: int, max_labels: int) -> list[LabelBox]:
    del width, height, max_labels
    placed: list[LabelBox] = []
    for node in sorted(nodes.values(), key=lambda n: (n.citations, n.occurrences), reverse=True):
        lines = wrap_label(node.label)
        font_size = label_font_size(node)
        text_w, text_h = label_dimensions(lines, font_size)
        placed.append(LabelBox(node.id, lines, node.x, node.y, text_w, text_h, "middle", font_size))
    return placed


def check_overlaps(
    nodes: dict[str, Node],
    labels: list[LabelBox],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    node_overlaps: list[str] = []
    node_list = list(nodes.values())
    for i, left in enumerate(node_list):
        for right in node_list[i + 1 :]:
            dist = math.hypot(left.x - right.x, left.y - right.y)
            allowed = left.r + right.r + 1.0
            if dist < allowed:
                node_overlaps.append(f"{left.label} overlaps {right.label} by {allowed - dist:.1f}px")

    label_overlaps: list[str] = []
    label_bounds_issues: list[str] = []
    label_node_overlaps: list[str] = []
    for i, left in enumerate(labels):
        left_rect = label_rect(left)
        if left_rect[0] < 0 or left_rect[1] < 70 or left_rect[2] > width or left_rect[3] > height - 24:
            label_bounds_issues.append(f"{nodes[left.node_id].label} label is outside canvas bounds")
        for right in labels[i + 1 :]:
            if rects_overlap(left_rect, label_rect(right), pad=2.0):
                label_overlaps.append(f"{nodes[left.node_id].label} label overlaps {nodes[right.node_id].label} label")
        for node in node_list:
            if node.id == left.node_id:
                continue
            if rect_overlaps_circle(left_rect, node, pad=1.0):
                label_node_overlaps.append(f"{nodes[left.node_id].label} label overlaps {node.label} node")

    passed = not (node_overlaps or label_overlaps or label_bounds_issues or label_node_overlaps)
    return {
        "passed": passed,
        "node_overlaps": node_overlaps[:50],
        "label_overlaps": label_overlaps[:50],
        "label_bounds_issues": label_bounds_issues[:50],
        "label_node_overlaps": label_node_overlaps[:50],
        "label_count": len(labels),
    }


def curved_path(source: Node, target: Node) -> str:
    mx = (source.x + target.x) / 2
    my = (source.y + target.y) / 2
    dx = target.x - source.x
    dy = target.y - source.y
    dist = math.sqrt(dx * dx + dy * dy) + 0.001
    curve_sign = -1 if stable_hash(source.id + target.id) % 2 else 1
    curve = min(84.0, max(16.0, dist * 0.18)) * curve_sign
    cx = mx - dy / dist * curve
    cy = my + dx / dist * curve
    return f"M {source.x:.2f},{source.y:.2f} Q {cx:.2f},{cy:.2f} {target.x:.2f},{target.y:.2f}"


def render_svg(
    nodes: dict[str, Node],
    edges: dict[tuple[str, str], Edge],
    *,
    title: str,
    width: int,
    height: int,
    labels: list[LabelBox],
) -> str:
    max_edge_citations = max((edge.citations for edge in edges.values()), default=1.0)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        '<filter id="softShadow" x="-40%" y="-40%" width="180%" height="180%">',
        '<feDropShadow dx="0" dy="1.5" stdDeviation="1.6" flood-color="#000000" flood-opacity="0.22"/>',
        "</filter>",
        "</defs>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2:.1f}" y="54" text-anchor="middle" font-family="Times New Roman, Georgia, serif" '
        f'font-size="30" font-weight="700" font-style="italic" fill="#111111">{escape(title)}</text>',
        '<g id="edges" fill="none">',
    ]

    for edge in sorted(edges.values(), key=lambda e: e.citations):
        source = nodes[edge.source]
        target = nodes[edge.target]
        color = TYPE_COLORS.get(source.type, "#777777")
        width_px = edge_width(edge, max_edge_citations)
        opacity = scale(edge.weight, 1.0, max((e.weight for e in edges.values()), default=1.0), 0.16, 0.56)
        parts.append(
            f'<path d="{curved_path(source, target)}" stroke="{color}" stroke-width="{width_px:.2f}" '
            f'stroke-opacity="{opacity:.3f}" stroke-linecap="round"/>'
        )
    parts.append("</g>")

    parts.append('<g id="nodes">')
    for node in sorted(nodes.values(), key=lambda n: n.r):
        color = TYPE_COLORS.get(node.type, "#777777")
        title_text = (
            f"{TYPE_LABELS.get(node.type, node.type)}: {node.label}\n"
            f"Papers: {len(node.papers)}\nOccurrences: {node.occurrences}\nCitation sum: {node.citations:.0f}"
        )
        parts.append(
            f'<circle cx="{node.x:.2f}" cy="{node.y:.2f}" r="{node.r:.2f}" fill="{color}" '
            f'fill-opacity="0.96" stroke="#111111" stroke-width="0.8" filter="url(#softShadow)">'
            f"<title>{escape(title_text)}</title></circle>"
        )
    parts.append("</g>")

    parts.append('<g id="labels" font-family="Times New Roman, Georgia, serif" fill="#000000">')
    for label_box in sorted(labels, key=lambda item: nodes[item.node_id].r, reverse=True):
        line_height = label_box.font_size * 1.18
        first_baseline = label_box.y - (len(label_box.lines) - 1) * line_height / 2
        parts.append(
            f'<text x="{label_box.x:.2f}" y="{label_box.y:.2f}" text-anchor="{label_box.anchor}" '
            f'font-size="{label_box.font_size:.1f}" '
            f'font-weight="700" paint-order="stroke" stroke="#111111" stroke-width="1.4" '
            f'stroke-linejoin="round" fill="#ffffff">'
        )
        for index, line in enumerate(label_box.lines):
            baseline = first_baseline + index * line_height
            parts.append(f'<tspan x="{label_box.x:.2f}" y="{baseline:.2f}">{escape(line)}</tspan>')
        parts.append("</text>")
    parts.append("</g>")

    legend_x = 42
    legend_y = height - 158
    parts.append(
        f'<g id="legend" font-family="Arial, sans-serif" font-size="15" fill="#111111">'
        f'<rect x="{legend_x - 18}" y="{legend_y - 30}" width="285" height="142" rx="10" fill="#ffffff" '
        f'stroke="#d0d0d0" stroke-width="1.2" fill-opacity="0.88"/>'
        f'<text x="{legend_x}" y="{legend_y - 7}" font-size="16" font-weight="700">Node type</text>'
    )
    for idx, node_type in enumerate(NODE_TYPES):
        y = legend_y + 20 + idx * 20
        parts.append(
            f'<circle cx="{legend_x + 8}" cy="{y - 5}" r="6.5" fill="{TYPE_COLORS[node_type]}" stroke="#111111" '
            f'stroke-width="0.5"/><text x="{legend_x + 24}" y="{y}">{escape(TYPE_LABELS[node_type])}</text>'
        )
    parts.append(
        f'<text x="{width - 42}" y="{height - 30}" text-anchor="end" font-family="Arial, sans-serif" '
        f'font-size="14" fill="#444444">Node size and link width scale with citation-weighted presence.</text>'
    )
    parts.append("</g></svg>\n")
    return "".join(parts)


def build_report(
    records: list[PaperRecord],
    nodes: dict[str, Node],
    edges: dict[tuple[str, str], Edge],
    warnings: list[str],
    overlap_checks: dict[str, Any],
) -> dict[str, Any]:
    by_type = {node_type: 0 for node_type in NODE_TYPES}
    for node in nodes.values():
        by_type[node.type] += 1
    top_nodes = [
        {
            "id": node.id,
            "label": node.label,
            "type": node.type,
            "citations": round(node.citations, 2),
            "papers": len(node.papers),
            "occurrences": node.occurrences,
        }
        for node in sorted(nodes.values(), key=lambda n: (n.citations, n.occurrences), reverse=True)[:20]
    ]
    return {
        "input_records": len(records),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes_by_type": by_type,
        "top_nodes": top_nodes,
        "warnings": warnings[:80],
        "overlap_checks": overlap_checks,
        "validation": {
            "passed": bool(nodes) and bool(edges) and overlap_checks["passed"],
            "has_author_nodes": by_type["author"] > 0,
            "has_topic_nodes": by_type["topic"] > 0,
            "has_affiliation_nodes": by_type["affiliation"] > 0,
            "overlap_checks_passed": overlap_checks["passed"],
        },
    }


def run_pipeline(
    records: list[PaperRecord],
    *,
    title: str,
    width: int,
    height: int,
    seed: int,
    max_nodes_per_type: int,
    min_node_citations: float,
    max_labels: int,
) -> tuple[str, dict[str, Any]]:
    nodes, edges, warnings = build_graph(records)
    nodes, edges = filter_graph(nodes, edges, max_nodes_per_type, min_node_citations)
    if not nodes or not edges:
        raise ValueError("graph is empty after filtering; lower --min-node-citations or increase --max-nodes-per-type")
    layout_graph(nodes, edges, seed)
    assign_node_sizes(nodes)
    expand_nodes_for_labels(nodes)
    normalize_to_canvas(nodes, width, height)
    resolve_node_overlaps(nodes, width, height)
    labels = place_labels(nodes, width=width, height=height, max_labels=max_labels)
    overlap_checks = check_overlaps(nodes, labels, width=width, height=height)
    svg = render_svg(nodes, edges, title=title, width=width, height=height, labels=labels)
    report = build_report(records, nodes, edges, warnings, overlap_checks)
    report["layout"] = {"width": width, "height": height, "seed": seed}
    report["style_contract"] = {
        "background": "white",
        "node_color_encodes": "node type",
        "node_size_encodes": "aggregated citation count",
        "edge_width_encodes": "citation-weighted co-occurrence",
        "edge_opacity_encodes": "co-occurrence count",
    }
    return svg, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a citation-weighted bibliometric connection graph.")
    parser.add_argument("--input", "-i", type=Path, help="JSON or CSV records. If omitted, built-in sample data is used.")
    parser.add_argument("--output", "-o", type=Path, help="Output SVG path.")
    parser.add_argument("--report", type=Path, help="Optional JSON report path.")
    parser.add_argument("--title", default="Bibliometric connection network", help="Figure title.")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-nodes-per-type", type=int, default=24)
    parser.add_argument("--min-node-citations", type=float, default=0.0)
    parser.add_argument(
        "--max-labels",
        type=int,
        default=48,
        help="Deprecated compatibility option; every retained node is labelled.",
    )
    parser.add_argument("--dump-sample", action="store_true", help="Print sample JSON input and exit.")
    parser.add_argument("--validate-only", action="store_true", help="Build the graph and report without writing SVG.")
    args = parser.parse_args()

    if args.dump_sample:
        print(json.dumps(SAMPLE_RECORDS, ensure_ascii=False, indent=2))
        return 0

    records = load_records(args.input)
    svg, report = run_pipeline(
        records,
        title=args.title,
        width=args.width,
        height=args.height,
        seed=args.seed,
        max_nodes_per_type=args.max_nodes_per_type,
        min_node_citations=args.min_node_citations,
        max_labels=args.max_labels,
    )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.validate_only:
        if not report["validation"]["passed"]:
            print("VALID=failed")
            return 1
        print("VALID=ok")
        return 0

    if not args.output:
        raise SystemExit("--output is required unless --dump-sample or --validate-only is used")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    if not report["validation"]["passed"]:
        print("VALID=failed")
        return 1
    print(f"OUTPUT={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
