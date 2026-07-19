#!/usr/bin/env python3
"""Render true author, institution, or country collaboration networks.

Unlike the legacy heterogeneous bibliometric map, this renderer creates edges
only when two entities co-occur in the same paper's real collaboration field.
It is intended for reference-review Figures 7/8 style reproduction.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.patches import FancyArrowPatch


DIMENSION_ALIASES = {
    "author": "authors",
    "authors": "authors",
    "institution": "institutions",
    "institutions": "institutions",
    "affiliation": "institutions",
    "affiliations": "institutions",
    "country": "countries",
    "countries": "countries",
    "region": "countries",
    "regions": "countries",
}
SINGULAR = {"authors": "author", "institutions": "institution", "countries": "country"}
PALETTE = ("#13A8C7", "#7C4DCE", "#20A875", "#E98245", "#D94B73", "#4477C4", "#9C7A2A", "#65758B")
MIN_MARKER_AREA = {"authors": 450.0, "institutions": 520.0, "countries": 380.0}
MAX_MARKER_AREA = {"authors": 2300.0, "institutions": 2400.0, "countries": 2200.0}
MIN_LABEL_FONT = {"authors": 14.0, "institutions": 14.0, "countries": 14.0}
PUBLICATION_WIDTH_IN = 6.6
PLACEHOLDERS = {"", "-", "--", "n/a", "na", "none", "null", "unknown", "unknown institution", "unknown country"}
COUNTRY_NAMES = {
    "AU": "Australia", "BD": "Bangladesh", "BR": "Brazil", "CA": "Canada", "CH": "Switzerland",
    "CN": "China", "CY": "Cyprus", "CZ": "Czech Republic", "DE": "Germany", "DK": "Denmark",
    "ES": "Spain", "FI": "Finland", "FR": "France", "GB": "United Kingdom", "GR": "Greece",
    "HK": "Hong Kong", "ID": "Indonesia", "IE": "Ireland", "IN": "India", "IR": "Iran",
    "IT": "Italy", "JO": "Jordan", "JP": "Japan", "KR": "South Korea", "MA": "Morocco",
    "MO": "Macao", "MX": "Mexico", "MY": "Malaysia", "NL": "Netherlands", "NO": "Norway",
    "NZ": "New Zealand", "OM": "Oman", "PH": "Philippines", "PT": "Portugal", "QA": "Qatar",
    "RO": "Romania", "RU": "Russia", "SA": "Saudi Arabia", "SE": "Sweden", "SG": "Singapore",
    "TH": "Thailand", "TR": "Turkey", "TW": "Taiwan", "US": "United States", "ZA": "South Africa",
}


def _split_string(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    delimiter = next((candidate for candidate in (";", "|", "\n") if candidate in text), None)
    return [text] if delimiter is None else [part.strip() for part in text.split(delimiter)]


def _labels(value: Any) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    labels: list[str] = []
    for item in raw:
        if isinstance(item, str):
            labels.extend(_split_string(item))
        elif isinstance(item, dict):
            candidate = item.get("display_name") or item.get("name") or item.get("author", {}).get("display_name")
            if candidate:
                labels.append(str(candidate).strip())
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        key = label.casefold().strip()
        if key not in PLACEHOLDERS and key not in seen:
            seen.add(key)
            result.append(label.strip())
    return result


def values_for(record: dict[str, Any], dimension: str) -> list[str]:
    if dimension == "authors":
        direct = _labels(record.get("authors") or record.get("author"))
        if direct:
            return direct
        return _labels([authorship.get("author", {}) for authorship in record.get("authorships", []) if isinstance(authorship, dict)])

    if dimension == "institutions":
        direct = _labels(record.get("institutions") or record.get("affiliations") or record.get("author_units"))
        if direct:
            return direct
        nested = []
        for authorship in record.get("authorships", []):
            if isinstance(authorship, dict):
                nested.extend(authorship.get("institutions", []))
        return _labels(nested)

    direct = _labels(record.get("countries") or record.get("country") or record.get("country_codes"))
    if direct:
        return direct
    nested: list[str] = []
    for authorship in record.get("authorships", []):
        if not isinstance(authorship, dict):
            continue
        nested.extend(_labels(authorship.get("countries")))
        for institution in authorship.get("institutions", []):
            if isinstance(institution, dict) and institution.get("country_code"):
                nested.append(str(institution["country_code"]))
    return _labels(nested)


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            records: Any = list(csv.DictReader(handle))
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get("records", data) if isinstance(data, dict) else data
    if not isinstance(records, list) or not records:
        raise ValueError("input must contain a non-empty record list")
    return [record for record in records if isinstance(record, dict)]


def build_graph(records: list[dict[str, Any]], dimension: str) -> tuple[nx.Graph, dict[str, Any]]:
    graph = nx.Graph()
    with_field = 0
    multi_party = 0
    all_nodes: set[str] = set()
    for record in records:
        nodes = sorted(set(values_for(record, dimension)), key=str.casefold)
        all_nodes.update(nodes)
        if not nodes:
            continue
        with_field += 1
        if len(nodes) > 1:
            multi_party += 1
        for node in nodes:
            if node not in graph:
                graph.add_node(node, publications=0)
            graph.nodes[node]["publications"] += 1
        for source, target in itertools.combinations(nodes, 2):
            weight = graph[source][target]["weight"] + 1 if graph.has_edge(source, target) else 1
            graph.add_edge(source, target, weight=weight)
    connected = [node for node in graph if graph.degree(node) > 0]
    graph = graph.subgraph(connected).copy()
    return graph, {
        "records_with_field": with_field,
        "coverage": with_field / len(records),
        "multi_party_records": multi_party,
        "raw_unique_nodes": len(all_nodes),
        "connected_nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "weighted_edges": sum(data["weight"] for _, _, data in graph.edges(data=True)),
        "components": nx.number_connected_components(graph) if graph else 0,
    }


def rank_nodes(graph: nx.Graph) -> list[str]:
    return sorted(
        graph,
        key=lambda node: (graph.nodes[node]["publications"], graph.degree(node, weight="weight"), graph.degree(node), node.casefold()),
        reverse=True,
    )


def select_top_connected(graph: nx.Graph, top_n: int) -> tuple[nx.Graph, list[str]]:
    candidates = rank_nodes(graph)[:top_n]
    selected = graph.subgraph(candidates).copy()
    isolated = sorted(nx.isolates(selected), key=str.casefold)
    selected.remove_nodes_from(isolated)
    return selected, isolated


def community_map(graph: nx.Graph) -> dict[str, int]:
    groups = list(nx.community.greedy_modularity_communities(graph, weight="weight"))
    groups.sort(key=lambda group: (-len(group), sorted(group, key=str.casefold)[0]))
    return {node: index for index, group in enumerate(groups) for node in group}


def spring_positions(graph: nx.Graph, seed: int) -> dict[str, np.ndarray]:
    positions = nx.spring_layout(graph, seed=seed, k=0.48 if graph.number_of_nodes() < 35 else 0.30, iterations=750, weight="weight")
    values = np.asarray(list(positions.values()), dtype=float)
    if values.size:
        center = values.mean(axis=0)
        span = np.ptp(values, axis=0)
        span[span == 0] = 1.0
        positions = {node: np.asarray([(point[0] - center[0]) / (span[0] / 2.0), (point[1] - center[1]) / (span[1] / 2.0)]) for node, point in positions.items()}
    return positions


def marker_sizes(graph: nx.Graph, dimension: str) -> dict[str, float]:
    values = [graph.nodes[node]["publications"] for node in graph]
    low, high = min(values), max(values)
    minimum = MIN_MARKER_AREA[dimension]
    maximum = MAX_MARKER_AREA[dimension]
    sizes = {}
    for node in graph:
        ratio = 0.0 if high == low else (graph.nodes[node]["publications"] - low) / (high - low)
        sizes[node] = minimum + (maximum - minimum) * math.pow(ratio, 0.78)
    return sizes


def separate_markers(fig, ax, positions: dict[str, np.ndarray], sizes: dict[str, float]) -> int:
    fig.canvas.draw()
    axes_box = ax.get_window_extent(fig.canvas.get_renderer())
    inverse = ax.transData.inverted()
    nodes = list(positions)
    centers = np.asarray([ax.transData.transform(positions[node]) for node in nodes], dtype=float)
    radii = np.asarray([math.sqrt(sizes[node] / math.pi) * fig.dpi / 72.0 for node in nodes])
    used = 0
    for iteration in range(600):
        used = iteration + 1
        deltas = np.zeros_like(centers)
        collisions = 0
        for left in range(len(nodes)):
            for right in range(left + 1, len(nodes)):
                vector = centers[right] - centers[left]
                distance = float(np.linalg.norm(vector))
                required = radii[left] + radii[right] + 3.0
                if distance >= required:
                    continue
                collisions += 1
                if distance < 1e-8:
                    angle = (left * 2.399963 + right * 0.754878) % (2 * math.pi)
                    unit = np.asarray([math.cos(angle), math.sin(angle)])
                    distance = 1.0
                else:
                    unit = vector / distance
                push = (required - distance) * 0.54
                deltas[left] -= unit * push
                deltas[right] += unit * push
        if collisions == 0:
            break
        centers += deltas
        for index, radius in enumerate(radii):
            centers[index, 0] = np.clip(centers[index, 0], axes_box.x0 + radius + 2, axes_box.x1 - radius - 2)
            centers[index, 1] = np.clip(centers[index, 1], axes_box.y0 + radius + 2, axes_box.y1 - radius - 2)
    for node, center in zip(nodes, centers):
        positions[node] = inverse.transform(center)
    return used


def _repel_labels(fig, ax, texts, iterations: int = 220) -> int:
    used = 0
    for iteration in range(iterations):
        used = iteration + 1
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [text.get_window_extent(renderer).expanded(1.035, 1.10) for text in texts]
        deltas = np.zeros((len(texts), 2), dtype=float)
        collisions = 0
        for left in range(len(boxes)):
            for right in range(left + 1, len(boxes)):
                if not boxes[left].overlaps(boxes[right]):
                    continue
                collisions += 1
                a, b = boxes[left], boxes[right]
                pen_x = min(a.x1, b.x1) - max(a.x0, b.x0)
                pen_y = min(a.y1, b.y1) - max(a.y0, b.y0)
                if pen_x < pen_y:
                    direction = -1 if (a.x0 + a.x1) <= (b.x0 + b.x1) else 1
                    deltas[left, 0] += direction * (pen_x + 5) * 0.56
                    deltas[right, 0] -= direction * (pen_x + 5) * 0.56
                else:
                    direction = -1 if (a.y0 + a.y1) <= (b.y0 + b.y1) else 1
                    deltas[left, 1] += direction * (pen_y + 4) * 0.56
                    deltas[right, 1] -= direction * (pen_y + 4) * 0.56
        axes_box = ax.get_window_extent(renderer)
        inverse = ax.transData.inverted()
        boundary_move = False
        for index, text in enumerate(texts):
            original = ax.transData.transform(text.get_position())
            current = original + deltas[index]
            box = boxes[index]
            current[0] = np.clip(current[0], axes_box.x0 + box.width / 2 + 4, axes_box.x1 - box.width / 2 - 4)
            current[1] = np.clip(current[1], axes_box.y0 + box.height / 2 + 4, axes_box.y1 - box.height / 2 - 4)
            boundary_move = boundary_move or bool(np.linalg.norm(current - original) > 0.25)
            text.set_position(inverse.transform(current))
        if collisions == 0 and not boundary_move:
            break
    return used


def layout_checks(fig, ax, graph: nx.Graph, positions, sizes, texts, labels, dimension: str) -> dict[str, Any]:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_box = ax.get_window_extent(renderer)
    boxes = [text.get_window_extent(renderer) for text in texts]
    label_overlaps = [[labels[i], labels[j]] for i in range(len(boxes)) for j in range(i + 1, len(boxes)) if boxes[i].overlaps(boxes[j])]
    out_of_bounds = [labels[i] for i, box in enumerate(boxes) if box.x0 < axes_box.x0 or box.x1 > axes_box.x1 or box.y0 < axes_box.y0 or box.y1 > axes_box.y1]
    nodes = list(graph)
    centers = {node: ax.transData.transform(positions[node]) for node in nodes}
    radii = {node: math.sqrt(sizes[node] / math.pi) * fig.dpi / 72.0 for node in nodes}
    node_overlaps = [[source, target] for i, source in enumerate(nodes) for target in nodes[i + 1 :] if np.linalg.norm(centers[source] - centers[target]) + 1.5 < radii[source] + radii[target]]
    labels_covering_own_node = [
        node
        for node, box in zip(labels, boxes)
        if box.x0 <= centers[node][0] <= box.x1 and box.y0 <= centers[node][1] <= box.y1
    ]
    marker_diameters = {
        node: 2.0 * math.sqrt(sizes[node] / math.pi) * fig.dpi / 72.0
        for node in graph
    }
    label_fonts = [float(text.get_fontsize()) for text in texts]
    publication_scale = PUBLICATION_WIDTH_IN / float(fig.get_figwidth())
    effective_marker_diameters = {
        node: diameter * publication_scale * 150.0 / fig.dpi
        for node, diameter in marker_diameters.items()
    }
    min_marker_area = min(sizes.values(), default=0.0)
    min_marker_diameter = min(marker_diameters.values(), default=0.0)
    min_label_font = min(label_fonts, default=0.0)
    readability = {
        "minimum_marker_area_pt2": round(min_marker_area, 2),
        "required_marker_area_pt2": MIN_MARKER_AREA[dimension],
        "minimum_marker_diameter_native_px": round(min_marker_diameter, 2),
        "required_marker_diameter_native_px": 45.0,
        "minimum_label_font_pt": round(min_label_font, 2),
        "required_label_font_pt": MIN_LABEL_FONT[dimension],
        "assumed_publication_width_in": PUBLICATION_WIDTH_IN,
        "effective_minimum_marker_diameter_at_150dpi_px": round(min(effective_marker_diameters.values(), default=0.0), 2),
        "required_effective_marker_diameter_at_150dpi_px": 18.0,
        "effective_minimum_label_font_pt": round(min_label_font * publication_scale, 2),
        "required_effective_label_font_pt": 6.0,
        "marker_size_passed": min_marker_area >= MIN_MARKER_AREA[dimension] and min_marker_diameter >= 45.0 and min(effective_marker_diameters.values(), default=0.0) >= 18.0,
        "label_font_passed": bool(label_fonts) and min_label_font >= MIN_LABEL_FONT[dimension] and min_label_font * publication_scale >= 6.0,
    }
    readability["passed"] = readability["marker_size_passed"] and readability["label_font_passed"]
    return {
        "passed": not label_overlaps and not out_of_bounds and not node_overlaps and not labels_covering_own_node and readability["passed"],
        "label_overlaps": label_overlaps,
        "out_of_bounds_labels": out_of_bounds,
        "node_overlaps": node_overlaps,
        "labels_covering_own_node": labels_covering_own_node,
        "unnamed_nodes": [node for node in graph if not node.strip()],
        "readability_contract": readability,
    }


def draw_network(
    graph: nx.Graph,
    dimension: str,
    output_dir: Path,
    seed: int,
    max_labels: int,
    input_stats: dict[str, Any],
    total_records: int,
) -> dict[str, Any]:
    community = community_map(graph)
    positions = spring_positions(graph, seed)
    sizes = marker_sizes(graph, dimension)
    labels = rank_nodes(graph)[:max_labels]
    plt.rcParams.update({"font.family": "DejaVu Serif", "svg.fonttype": "none"})
    fig = plt.figure(figsize=(15.2, 10.4), dpi=160, facecolor="#FBFCFE")
    ax = fig.add_axes([0.035, 0.105, 0.93, 0.78])
    ax.set_xlim(-1.34, 1.34)
    ax.set_ylim(-1.18, 1.18)
    ax.set_axis_off()
    separation_iterations = separate_markers(fig, ax, positions, sizes)
    for radius, alpha in ((0.46, 0.55), (0.80, 0.42), (1.13, 0.30)):
        ax.add_patch(plt.Circle((0, 0), radius, fill=False, color="#D9E1EA", lw=0.8, alpha=alpha, zorder=0))
    max_weight = max(nx.get_edge_attributes(graph, "weight").values(), default=1)
    for index, (source, target, data) in enumerate(graph.edges(data=True)):
        ax.add_patch(FancyArrowPatch(
            positions[source], positions[target], arrowstyle="-",
            connectionstyle=f"arc3,rad={(0.055 + 0.018 * (index % 4)) * (-1 if index % 2 else 1)}",
            linewidth=0.75 + 2.7 * data["weight"] / max_weight,
            color=PALETTE[community[source] % len(PALETTE)], alpha=0.38, zorder=1,
        ))
    for node in graph:
        ax.scatter([positions[node][0]], [positions[node][1]], s=sizes[node], color=PALETTE[community[node] % len(PALETTE)], edgecolors="white", linewidths=1.2, alpha=0.94, zorder=3)

    texts = []
    for index, node in enumerate(labels):
        shown = COUNTRY_NAMES.get(node.upper(), node) if dimension == "countries" else node
        shown = "\n".join(textwrap.wrap(shown, width=30, break_long_words=False, break_on_hyphens=False))
        point = np.array(positions[node], dtype=float, copy=True)
        norm = float(np.linalg.norm(point))
        direction = point / norm if norm >= 0.14 else np.asarray([math.cos(index * 2.399963), math.sin(index * 2.399963)])
        offset = 0.16 if dimension == "countries" else 0.32
        proposed = point + direction * offset
        if abs(proposed[0]) > 1.08 or abs(proposed[1]) > 0.92:
            direction = -direction
        point += direction * offset
        texts.append(ax.text(
            point[0], point[1], shown, ha="center", va="center",
            fontsize=max(MIN_LABEL_FONT[dimension], 7.4 + 0.75 * math.sqrt(graph.nodes[node]["publications"])), fontweight="semibold",
            color="#172033", linespacing=0.92,
            bbox={"boxstyle": "round,pad=0.14", "facecolor": "white", "edgecolor": "none", "alpha": 0.68}, zorder=5,
        ))
    repel_iterations = _repel_labels(fig, ax, texts)
    for node, label in zip(labels, texts):
        tx, ty = label.get_position()
        nx_, ny_ = positions[node]
        if math.hypot(tx - nx_, ty - ny_) > 0.035:
            ax.plot([nx_, tx], [ny_, ty], color="#7D8A9C", linewidth=0.55, alpha=0.55, zorder=2)

    singular = SINGULAR[dimension]
    title = "COUNTRY / REGION COLLABORATION NETWORK" if dimension == "countries" else f"{singular.upper()} COLLABORATION NETWORK"
    fig.text(0.05, 0.955, title, fontsize=19.0 if dimension == "countries" else 21.5, fontweight="bold", color="#10213B", ha="left", va="top")
    fig.text(0.05, 0.917, "Observed co-occurrence ties only; isolated ranked candidates are omitted.", fontsize=10.5, color="#536274", ha="left", va="top")
    fig.text(0.95, 0.947, f"{graph.number_of_nodes()} NODES  ·  {graph.number_of_edges()} EDGES  ·  METADATA {input_stats['records_with_field']}/{total_records}", fontsize=9.2, fontweight="bold", color="#31516F", ha="right", va="top", bbox={"boxstyle": "round,pad=0.35", "facecolor": "#EAF2F8", "edgecolor": "#C7D7E5"})
    fig.text(0.05, 0.045, "NODE AREA  publication count     ·     LINE WIDTH  collaboration frequency     ·     COLOR  detected collaboration community", fontsize=9.3, color="#4E5B6B", ha="left", va="bottom")

    checks = layout_checks(fig, ax, graph, positions, sizes, texts, labels, dimension)
    checks["node_separation_iterations"] = separation_iterations
    checks["label_repel_iterations"] = repel_iterations
    stem = f"{singular}_collaboration_network"
    svg_path, png_path = output_dir / f"{stem}.svg", output_dir / f"{stem}.png"
    fig.savefig(svg_path, facecolor=fig.get_facecolor())
    fig.savefig(png_path, facecolor=fig.get_facecolor(), dpi=160)
    plt.close(fig)
    return {
        "visible_nodes": graph.number_of_nodes(), "labelled_nodes": len(labels), "edge_count": graph.number_of_edges(),
        "weighted_edge_count": sum(data["weight"] for _, _, data in graph.edges(data=True)), "communities": len(set(community.values())),
        "layout_checks": checks, "outputs": {"svg": str(svg_path.resolve()), "png": str(png_path.resolve())},
    }


def run_pipeline(
    records: list[dict[str, Any]], *, output_dir: Path, dimensions: list[str], top_n: int,
    max_labels: int, min_coverage: float, min_multi_party_records: int, seed: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    networks: dict[str, Any] = {}
    skipped: dict[str, Any] = {}
    for offset, dimension in enumerate(dimensions):
        full_graph, input_stats = build_graph(records, dimension)
        reasons = []
        if input_stats["coverage"] < min_coverage:
            reasons.append(f"coverage {input_stats['coverage']:.3f} is below minimum {min_coverage:.3f}")
        if input_stats["multi_party_records"] < min_multi_party_records:
            reasons.append(f"only {input_stats['multi_party_records']} multi-party records; minimum is {min_multi_party_records}")
        if full_graph.number_of_edges() == 0:
            reasons.append("no observed collaboration edges")
        if reasons:
            skipped[dimension] = {"input_stats": input_stats, "reasons": reasons}
            continue
        selected, isolated = select_top_connected(full_graph, top_n)
        if selected.number_of_edges() == 0:
            skipped[dimension] = {"input_stats": input_stats, "reasons": ["top-ranked induced graph has no connected edges"]}
            continue
        networks[dimension] = {
            "input_stats": input_stats,
            "selection": {"top_n_candidates": min(top_n, full_graph.number_of_nodes()), "isolated_candidates_omitted": isolated},
            **draw_network(selected, dimension, output_dir, seed + offset * 101, max_labels, input_stats, len(records)),
        }
    passed = bool(networks) and not skipped and all(item["layout_checks"]["passed"] for item in networks.values())
    return {
        "input_records": len(records),
        "requested_dimensions": dimensions,
        "semantic_contract": "Every edge is a true within-record co-authorship, co-institution, or co-country tie; heterogeneous author/topic/journal/year edges are forbidden.",
        "networks": networks,
        "skipped": skipped,
        "validation": {
            "true_collaboration_edges_only": True,
            "no_inferred_entities_or_edges": True,
            "all_requested_dimensions_rendered": not skipped,
            "all_layout_checks_passed": bool(networks) and all(item["layout_checks"]["passed"] for item in networks.values()),
            "all_minimum_node_sizes_passed": bool(networks) and all(item["layout_checks"]["readability_contract"]["marker_size_passed"] for item in networks.values()),
            "all_minimum_label_fonts_passed": bool(networks) and all(item["layout_checks"]["readability_contract"]["label_font_passed"] for item in networks.values()),
            "passed": passed,
        },
    }


def parse_dimensions(value: str) -> list[str]:
    result = []
    for token in value.split(","):
        key = DIMENSION_ALIASES.get(token.strip().lower())
        if not key:
            raise argparse.ArgumentTypeError(f"unsupported dimension: {token}")
        if key not in result:
            result.append(key)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Render true collaboration networks from publication metadata.")
    parser.add_argument("--input", "-i", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dimensions", type=parse_dimensions, default=parse_dimensions("countries,institutions"))
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--max-labels", type=int, default=20)
    parser.add_argument("--min-coverage", type=float, default=0.20)
    parser.add_argument("--min-multi-party-records", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260718)
    args = parser.parse_args()
    records = load_records(args.input)
    report = run_pipeline(
        records, output_dir=args.output_dir, dimensions=args.dimensions, top_n=args.top_n,
        max_labels=args.max_labels, min_coverage=args.min_coverage,
        min_multi_party_records=args.min_multi_party_records, seed=args.seed,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["validation"], indent=2))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
