from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_collaboration_networks import build_graph, run_pipeline, values_for  # noqa: E402


RECORDS = [
    {"title": "A", "authors": ["Alice", "Bob"], "institutions": ["Alpha University", "Beta University"], "countries": ["US", "CA"]},
    {"title": "B", "authors": ["Alice", "Cara"], "institutions": ["Alpha University", "Gamma Institute"], "countries": ["US", "GB"]},
    {"title": "C", "authors": ["Bob", "Cara"], "institutions": ["Beta University", "Gamma Institute"], "countries": ["CA", "GB"]},
    {"title": "D", "authors": ["Alice", "Bob"], "institutions": ["Alpha University", "Beta University"], "countries": ["US", "CA"]},
]


def test_build_graph_uses_only_same_dimension_collaboration_edges() -> None:
    graph, stats = build_graph(RECORDS, "countries")

    assert set(graph) == {"US", "CA", "GB"}
    assert graph["US"]["CA"]["weight"] == 2
    assert graph.number_of_edges() == 3
    assert stats["records_with_field"] == 4
    assert stats["multi_party_records"] == 4


def test_pipeline_renders_reference_style_country_and_institution_networks(tmp_path: Path) -> None:
    report = run_pipeline(
        RECORDS,
        output_dir=tmp_path,
        dimensions=["countries", "institutions"],
        top_n=30,
        max_labels=12,
        min_coverage=0.20,
        min_multi_party_records=3,
        seed=17,
    )

    assert report["validation"]["passed"] is True
    assert report["validation"]["true_collaboration_edges_only"] is True
    assert set(report["networks"]) == {"countries", "institutions"}
    assert report["networks"]["countries"]["layout_checks"]["passed"] is True
    assert report["networks"]["institutions"]["layout_checks"]["passed"] is True
    assert report["validation"]["all_minimum_node_sizes_passed"] is True
    assert report["validation"]["all_minimum_label_fonts_passed"] is True
    assert report["networks"]["institutions"]["layout_checks"]["readability_contract"]["minimum_marker_diameter_native_px"] >= 45
    assert (tmp_path / "country_collaboration_network.svg").exists()
    assert (tmp_path / "institution_collaboration_network.png").exists()
    json.dumps(report, ensure_ascii=False)


def test_pipeline_rejects_insufficient_affiliation_coverage(tmp_path: Path) -> None:
    sparse = [{"title": f"Paper {index}", "authors": ["A", "B"]} for index in range(8)]
    sparse[0]["countries"] = ["US", "CA"]
    report = run_pipeline(
        sparse,
        output_dir=tmp_path,
        dimensions=["countries"],
        top_n=30,
        max_labels=10,
        min_coverage=0.20,
        min_multi_party_records=2,
        seed=3,
    )

    assert report["validation"]["passed"] is False
    assert "countries" in report["skipped"]
    assert report["networks"] == {}


def test_nested_openalex_authorship_fields_are_supported() -> None:
    record = {
        "authorships": [
            {"author": {"display_name": "Alice"}, "countries": ["US"], "institutions": [{"display_name": "Alpha", "country_code": "US"}]},
            {"author": {"display_name": "Bob"}, "countries": ["CA"], "institutions": [{"display_name": "Beta", "country_code": "CA"}]},
        ]
    }

    assert values_for(record, "authors") == ["Alice", "Bob"]
    assert values_for(record, "institutions") == ["Alpha", "Beta"]
    assert values_for(record, "countries") == ["US", "CA"]
