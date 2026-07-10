from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_bibliometric_network import build_graph, load_records, run_pipeline  # noqa: E402


def test_bibliometric_network_pipeline_renders_svg() -> None:
    records = load_records(ROOT / "tools" / "examples" / "aied_bibliometric_network_records.json")
    svg, report = run_pipeline(
        records,
        title="Test bibliometric network",
        width=900,
        height=680,
        seed=7,
        max_nodes_per_type=10,
        min_node_citations=0,
        max_labels=24,
    )

    assert svg.startswith("<svg")
    assert "<path" in svg
    assert "<circle" in svg
    assert "Citation sum" in svg
    assert report["validation"]["passed"] is True
    assert report["validation"]["overlap_checks_passed"] is True
    assert report["overlap_checks"]["node_overlaps"] == []
    assert report["overlap_checks"]["label_overlaps"] == []
    assert report["overlap_checks"]["label_bounds_issues"] == []
    assert report["overlap_checks"]["label_node_overlaps"] == []
    assert report["overlap_checks"]["label_count"] == report["node_count"]
    assert report["nodes_by_type"]["author"] > 0
    assert report["nodes_by_type"]["topic"] > 0
    assert report["nodes_by_type"]["affiliation"] > 0


def test_bibliometric_network_report_is_json_serializable() -> None:
    records = load_records(None)
    _, report = run_pipeline(
        records,
        title="Sample",
        width=900,
        height=680,
        seed=7,
        max_nodes_per_type=10,
        min_node_citations=0,
        max_labels=24,
    )

    encoded = json.dumps(report, ensure_ascii=False)
    assert "edge_width_encodes" in encoded


def test_bibliometric_network_omits_missing_or_placeholder_metadata_nodes() -> None:
    records = load_records(None)
    records[0].journal = "Unknown source"
    records[0].year = ""
    records[0].authors.append("N/A")

    nodes, _, _ = build_graph(records)

    assert all(node.label.strip() for node in nodes.values())
    assert all(node.label.lower() not in {"unknown source", "unknown year", "n/a"} for node in nodes.values())
