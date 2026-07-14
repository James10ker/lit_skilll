#!/usr/bin/env python3
"""Render the plan Task 2 heterogeneous graphs and Task 4 topic-year chart."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


NODE_TYPES = ("journal", "author", "topic", "year", "paper", "citation")
NODE_TITLES = {
    "journal": "Journals",
    "author": "Authors",
    "topic": "Topics",
    "year": "Years",
    "paper": "Papers",
    "citation": "Citation bands",
}
NODE_COLORS = {
    "journal": "#f2a65a",
    "author": "#3aaed8",
    "topic": "#70b85d",
    "year": "#9b7ede",
    "paper": "#e06c75",
    "citation": "#5bb8a8",
}
EDGE_TYPES = (
    "author-journal",
    "author-topic",
    "topic-year",
    "year-paper",
    "paper-topic",
    "paper-citation",
)
EDGE_COLORS = {
    "author-journal": "#c47b32",
    "author-topic": "#208cb5",
    "topic-year": "#569448",
    "year-paper": "#7458bc",
    "paper-topic": "#bc4650",
    "paper-citation": "#318f81",
}
PLACEHOLDERS = {"", "-", "--", "n/a", "na", "none", "null", "unknown"}
REVIEW_TERMS = (
    "review",
    "survey",
    "meta-analysis",
    "meta analysis",
    "bibliometric",
    "scoping",
    "systematic revision",
)


@dataclass(frozen=True)
class Record:
    key: str
    title: str
    authors: tuple[str, ...]
    year: int
    journal: str
    topic: str
    citations: int
    work_type: str
    abstract: str

    @property
    def is_review(self) -> bool:
        haystack = f"{self.title} {self.work_type}".lower()
        return any(term in haystack for term in REVIEW_TERMS)


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    label: str
    weight: float
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    type: str
    weight: int


def _split(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        raw = value
    elif value is None:
        raw = []
    else:
        raw = str(value).replace("|", ";").split(";")
    seen: set[str] = set()
    values: list[str] = []
    for item in raw:
        label = str(item).strip()
        normalized = label.lower()
        if normalized not in PLACEHOLDERS and normalized not in seen:
            seen.add(normalized)
            values.append(label)
    return tuple(values)


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _named(value: Any) -> str:
    text = str(value or "").strip()
    return text if text.lower() not in PLACEHOLDERS else ""


def load_records(path: Path) -> list[Record]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_records = payload.get("records", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_records, list):
        raise ValueError("input must be a JSON list or an object with a records list")
    records: list[Record] = []
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            continue
        title = _named(raw.get("title") or raw.get("paper_title"))
        year = _integer(raw.get("publication_year") or raw.get("year"))
        authors = _split(raw.get("authors") or raw.get("author"))
        journal = _named(raw.get("source_name") or raw.get("journal") or raw.get("source"))
        topic = _named(raw.get("primary_topic_label") or raw.get("primary_topic"))
        if not title or not year or not authors or not journal or not topic:
            continue
        records.append(
            Record(
                key=_named(raw.get("bibkey")) or f"record-{index + 1}",
                title=title,
                authors=authors,
                year=year,
                journal=journal,
                topic=topic,
                citations=max(0, _integer(raw.get("cited_by_count") or raw.get("citations"))),
                work_type=_named(raw.get("work_type")),
                abstract=_named(raw.get("abstract")),
            )
        )
    if not records:
        raise ValueError("no records contain all fields required by plan Task 2")
    return records


def citation_band(value: int) -> str:
    if value >= 500:
        return "500+ citations"
    if value >= 200:
        return "200-499 citations"
    if value >= 50:
        return "50-199 citations"
    if value >= 1:
        return "1-49 citations"
    return "0 citations"


def _shorten(text: str, limit: int = 58) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _node_id(node_type: str, label: str) -> str:
    return f"{node_type}:{label.lower()}"


def _ranked(counter: Counter[str], limit: int) -> list[str]:
    return [label for label, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))[:limit]]


def build_partition_graph(records: list[Record], *, max_papers: int) -> tuple[list[Node], list[Edge], dict[str, Any]]:
    selected = sorted(records, key=lambda record: (-record.citations, record.year, record.title.lower()))[:max_papers]
    authors = Counter(author for record in selected for author in record.authors)
    journals = Counter(record.journal for record in selected)
    topics = Counter(record.topic for record in selected)
    years = Counter(str(record.year) for record in selected)
    papers = Counter(_shorten(record.title) for record in selected)
    citations = Counter(citation_band(record.citations) for record in selected)
    labels_by_type = {
        "journal": _ranked(journals, 9),
        "author": _ranked(authors, 12),
        "topic": _ranked(topics, 8),
        "year": _ranked(years, 10),
        "paper": _ranked(papers, max_papers),
        "citation": _ranked(citations, 5),
    }

    width, top, bottom, node_w, node_h = 1920.0, 154.0, 88.0, 252.0, 58.0
    max_rows = max(len(labels) for labels in labels_by_type.values())
    height = max(980.0, top + bottom + max_rows * 78.0)
    lane_width = width / len(NODE_TYPES)
    nodes: list[Node] = []
    for lane, node_type in enumerate(NODE_TYPES):
        labels = labels_by_type[node_type]
        usable = height - top - bottom
        step = usable / max(1, len(labels))
        for index, label in enumerate(labels):
            counter = {
                "journal": journals,
                "author": authors,
                "topic": topics,
                "year": years,
                "paper": papers,
                "citation": citations,
            }[node_type]
            nodes.append(
                Node(
                    id=_node_id(node_type, label),
                    type=node_type,
                    label=label,
                    weight=float(counter[label]),
                    x=lane_width * (lane + 0.5),
                    y=top + step * (index + 0.5),
                    width=node_w,
                    height=node_h,
                )
            )

    kept = {node.id for node in nodes}
    edge_counts: Counter[tuple[str, str, str]] = Counter()
    for record in selected:
        paper_label = _shorten(record.title)
        paper_id = _node_id("paper", paper_label)
        topic_id = _node_id("topic", record.topic)
        year_id = _node_id("year", str(record.year))
        journal_id = _node_id("journal", record.journal)
        citation_id = _node_id("citation", citation_band(record.citations))
        relationships = [
            (year_id, paper_id, "year-paper"),
            (paper_id, topic_id, "paper-topic"),
            (topic_id, year_id, "topic-year"),
            (paper_id, citation_id, "paper-citation"),
        ]
        for author in record.authors:
            author_id = _node_id("author", author)
            relationships.extend(
                [
                    (author_id, topic_id, "author-topic"),
                    (author_id, journal_id, "author-journal"),
                ]
            )
        for source, target, edge_type in relationships:
            if source in kept and target in kept:
                edge_counts[(source, target, edge_type)] += 1

    edges = [Edge(source, target, edge_type, weight) for (source, target, edge_type), weight in edge_counts.items()]
    node_counts = {node_type: sum(node.type == node_type for node in nodes) for node_type in NODE_TYPES}
    edge_type_counts = {edge_type: sum(edge.type == edge_type for edge in edges) for edge_type in EDGE_TYPES}
    checks = validate_layout(nodes, edges, width=width, height=height)
    metrics = {
        "selected_records": len(selected),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes_by_type": node_counts,
        "edges_by_type": edge_type_counts,
        "canvas": {"width": int(width), "height": int(height)},
        "layout_checks": checks,
    }
    return nodes, edges, metrics


def _rect(node: Node) -> tuple[float, float, float, float]:
    return (
        node.x - node.width / 2,
        node.y - node.height / 2,
        node.x + node.width / 2,
        node.y + node.height / 2,
    )


def validate_layout(nodes: list[Node], edges: list[Edge], *, width: float, height: float) -> dict[str, Any]:
    unnamed = [node.id for node in nodes if not node.label.strip() or node.label.lower() in PLACEHOLDERS]
    overlaps: list[str] = []
    for index, left in enumerate(nodes):
        left_rect = _rect(left)
        for right in nodes[index + 1 :]:
            right_rect = _rect(right)
            if not (
                left_rect[2] + 4 <= right_rect[0]
                or right_rect[2] + 4 <= left_rect[0]
                or left_rect[3] + 4 <= right_rect[1]
                or right_rect[3] + 4 <= left_rect[1]
            ):
                overlaps.append(f"{left.id}|{right.id}")
    out_of_bounds = [
        node.id
        for node in nodes
        if _rect(node)[0] < 0 or _rect(node)[1] < 96 or _rect(node)[2] > width or _rect(node)[3] > height
    ]
    node_types = {node.type for node in nodes}
    edge_types = {edge.type for edge in edges}
    return {
        "passed": not unnamed and not overlaps and not out_of_bounds and node_types == set(NODE_TYPES) and edge_types == set(EDGE_TYPES),
        "unnamed_nodes": unnamed,
        "node_overlaps": overlaps,
        "out_of_bounds_nodes": out_of_bounds,
        "all_six_node_types_present": node_types == set(NODE_TYPES),
        "all_six_edge_types_present": edge_types == set(EDGE_TYPES),
    }


def _wrap(text: str, max_chars: int = 24, max_lines: int = 3) -> tuple[str, ...]:
    words = text.split()
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
    if not lines:
        lines = [text]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max_chars - 3].rstrip() + "..."
    return tuple(lines)


def render_network_svg(nodes: list[Node], edges: list[Edge], *, title: str, subtitle: str) -> str:
    width = 1920
    height = int(max(node.y + node.height / 2 for node in nodes) + 88)
    node_map = {node.id: node for node in nodes}
    max_weight = max((edge.weight for edge in edges), default=1)
    lane_width = width / len(NODE_TYPES)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="42" text-anchor="middle" font-family="Arial, sans-serif" font-size="30" font-weight="700">{escape(title)}</text>',
        f'<text x="{width / 2}" y="72" text-anchor="middle" font-family="Arial, sans-serif" font-size="17" fill="#444444">{escape(subtitle)}</text>',
    ]
    for lane, node_type in enumerate(NODE_TYPES):
        x = lane * lane_width
        parts.append(f'<rect x="{x + 8:.1f}" y="94" width="{lane_width - 16:.1f}" height="{height - 110}" rx="6" fill="{NODE_COLORS[node_type]}" fill-opacity="0.055"/>')
        parts.append(f'<text x="{x + lane_width / 2:.1f}" y="122" text-anchor="middle" font-family="Arial, sans-serif" font-size="19" font-weight="700" fill="#222222">{NODE_TITLES[node_type]}</text>')

    parts.append('<g id="edges" fill="none">')
    for edge in sorted(edges, key=lambda item: item.weight):
        source, target = node_map[edge.source], node_map[edge.target]
        sx = source.x + (source.width / 2 if target.x > source.x else -source.width / 2)
        tx = target.x - (target.width / 2 if target.x > source.x else -target.width / 2)
        opacity = 0.14 + 0.30 * edge.weight / max_weight
        stroke_width = 0.7 + 3.2 * math.sqrt(edge.weight / max_weight)
        if edge.type == "paper-topic":
            control_y = 132.0
            path = f"M {sx:.1f},{source.y:.1f} C {sx:.1f},{control_y:.1f} {tx:.1f},{control_y:.1f} {tx:.1f},{target.y:.1f}"
        else:
            midpoint = (sx + tx) / 2
            path = f"M {sx:.1f},{source.y:.1f} C {midpoint:.1f},{source.y:.1f} {midpoint:.1f},{target.y:.1f} {tx:.1f},{target.y:.1f}"
        parts.append(f'<path d="{path}" stroke="{EDGE_COLORS[edge.type]}" stroke-width="{stroke_width:.2f}" stroke-opacity="{opacity:.3f}"/>')
    parts.append('</g><g id="nodes">')
    for node in nodes:
        x, y = node.x - node.width / 2, node.y - node.height / 2
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{node.width:.1f}" height="{node.height:.1f}" rx="6" fill="{NODE_COLORS[node.type]}" stroke="#25313a" stroke-width="1.0"/>')
        lines = _wrap(node.label)
        line_height = 14.0
        first_y = node.y - (len(lines) - 1) * line_height / 2 + 4
        parts.append(f'<text x="{node.x:.1f}" y="{first_y:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12.5" font-weight="700" fill="#111111">')
        for index, line in enumerate(lines):
            parts.append(f'<tspan x="{node.x:.1f}" y="{first_y + index * line_height:.1f}">{escape(line)}</tspan>')
        parts.append('</text>')
    parts.append('</g>')

    legend_y = height - 27
    legend_x = 34
    for index, edge_type in enumerate(EDGE_TYPES):
        x = legend_x + index * 305
        parts.append(f'<line x1="{x}" y1="{legend_y - 5}" x2="{x + 36}" y2="{legend_y - 5}" stroke="{EDGE_COLORS[edge_type]}" stroke-width="3"/>')
        parts.append(f'<text x="{x + 44}" y="{legend_y}" font-family="Arial, sans-serif" font-size="14" fill="#222222">{edge_type}</text>')
    parts.append('</svg>\n')
    return "".join(parts)


def render_topic_year_svg(records: list[Record], *, start_year: int, end_year: int) -> tuple[str, dict[str, Any]]:
    topics = _ranked(Counter(record.topic for record in records if start_year <= record.year <= end_year), 8)
    years = list(range(start_year, end_year + 1))
    counts = Counter((record.topic, record.year) for record in records if start_year <= record.year <= end_year)
    totals = Counter(record.year for record in records if start_year <= record.year <= end_year)
    proportions = {
        (topic, year): (counts[(topic, year)] / totals[year] if totals[year] else 0.0)
        for topic in topics
        for year in years
    }
    max_value = max(proportions.values(), default=1.0)
    width, height = 1600, 180 + len(topics) * 86
    left, right, top, bottom = 390.0, 90.0, 105.0, 80.0
    cell_w = (width - left - right) / len(years)
    cell_h = (height - top - bottom) / len(topics)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="40" text-anchor="middle" font-family="Arial, sans-serif" font-size="29" font-weight="700">Annual topic intensity</text>',
        f'<text x="{width / 2}" y="68" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" fill="#444444">Cell values are primary-topic shares within each publication year</text>',
    ]
    for row, topic in enumerate(topics):
        y = top + row * cell_h
        parts.append(f'<text x="{left - 18}" y="{y + cell_h / 2 + 5:.1f}" text-anchor="end" font-family="Arial, sans-serif" font-size="15" font-weight="700">{escape(_shorten(topic, 42))}</text>')
        for column, year in enumerate(years):
            x = left + column * cell_w
            value = proportions[(topic, year)]
            ratio = value / max_value if max_value else 0.0
            red = int(246 - 129 * ratio)
            green = int(249 - 105 * ratio)
            blue = int(244 - 164 * ratio)
            fill = f"#{red:02x}{green:02x}{blue:02x}"
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w - 2:.1f}" height="{cell_h - 2:.1f}" fill="{fill}" stroke="#ffffff"/>')
            if value:
                color = "#ffffff" if ratio > 0.55 else "#172026"
                parts.append(f'<text x="{x + cell_w / 2:.1f}" y="{y + cell_h / 2 + 5:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="{color}">{value * 100:.0f}%</text>')
    for column, year in enumerate(years):
        x = left + (column + 0.5) * cell_w
        parts.append(f'<text x="{x:.1f}" y="{height - 36}" text-anchor="middle" font-family="Arial, sans-serif" font-size="15" font-weight="700">{year}</text>')
    parts.append('</svg>\n')
    metrics = {
        "start_year": start_year,
        "end_year": end_year,
        "topics": topics,
        "years": years,
        "record_count": sum(totals.values()),
        "max_annual_topic_share": max_value,
    }
    return "".join(parts), metrics


def _write_svg_and_png(svg: str, svg_path: Path) -> Path | None:
    svg_path.write_text(svg, encoding="utf-8")
    converter = shutil.which("rsvg-convert")
    if converter is None:
        return None
    png_path = svg_path.with_suffix(".png")
    subprocess.run([converter, str(svg_path), "-o", str(png_path)], check=True)
    return png_path


def run(
    records: list[Record],
    *,
    output_dir: Path,
    report_path: Path,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    review_records = [record for record in records if record.is_review]
    non_review_records = [record for record in records if not record.is_review]
    partitions = {
        "review": (review_records, 14, "Review literature relationship graph"),
        "non_review": (non_review_records, 18, "Non-review literature relationship graph"),
    }
    outputs: dict[str, str] = {}
    partition_reports: dict[str, Any] = {}
    for name, (partition_records, max_papers, title) in partitions.items():
        nodes, edges, metrics = build_partition_graph(partition_records, max_papers=max_papers)
        svg = render_network_svg(
            nodes,
            edges,
            title=title,
            subtitle="Six node types and six evidence relationships required by plan Task 2",
        )
        svg_path = output_dir / f"{name}_evidence_graph.svg"
        png_path = _write_svg_and_png(svg, svg_path)
        outputs[f"{name}_graph_svg"] = str(svg_path.resolve())
        if png_path:
            outputs[f"{name}_graph_png"] = str(png_path.resolve())
        partition_reports[name] = metrics

    topic_svg, topic_metrics = render_topic_year_svg(records, start_year=start_year, end_year=end_year)
    topic_svg_path = output_dir / "topic_year_evolution.svg"
    topic_png_path = _write_svg_and_png(topic_svg, topic_svg_path)
    outputs["topic_year_svg"] = str(topic_svg_path.resolve())
    if topic_png_path:
        outputs["topic_year_png"] = str(topic_png_path.resolve())

    passed = (
        bool(review_records)
        and bool(non_review_records)
        and all(report["layout_checks"]["passed"] for report in partition_reports.values())
        and topic_metrics["record_count"] > 0
    )
    report = {
        "input_records": len(records),
        "review_records": len(review_records),
        "non_review_records": len(non_review_records),
        "task_2_graphs": partition_reports,
        "task_4_topic_year": topic_metrics,
        "outputs": outputs,
        "validation": {
            "passed": passed,
            "two_graphs_rendered": len(partition_reports) == 2,
            "six_node_types_per_graph": all(report["layout_checks"]["all_six_node_types_present"] for report in partition_reports.values()),
            "six_edge_types_per_graph": all(report["layout_checks"]["all_six_edge_types_present"] for report in partition_reports.values()),
            "no_unnamed_nodes": all(not report["layout_checks"]["unnamed_nodes"] for report in partition_reports.values()),
            "no_node_overlaps": all(not report["layout_checks"]["node_overlaps"] for report in partition_reports.values()),
            "topic_year_rendered": topic_metrics["record_count"] > 0,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(
        load_records(args.input),
        output_dir=args.output_dir,
        report_path=args.report,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
