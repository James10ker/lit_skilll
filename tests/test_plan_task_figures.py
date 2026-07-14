from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_plan_task_figures import load_records, run  # noqa: E402


def test_plan_task_figures_render_two_six_type_graphs_and_topic_year() -> None:
    records = load_records(ROOT / "outputs" / "aied_cc_trial_en_v2" / "data" / "prepared_records.json")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        report = run(
            records,
            output_dir=root / "figures",
            report_path=root / "report.json",
            start_year=2015,
            end_year=2024,
        )

        assert report["validation"]["passed"] is True
        assert report["validation"]["two_graphs_rendered"] is True
        assert report["validation"]["six_node_types_per_graph"] is True
        assert report["validation"]["six_edge_types_per_graph"] is True
        assert report["validation"]["no_unnamed_nodes"] is True
        assert report["validation"]["no_node_overlaps"] is True
        assert (root / "figures" / "review_evidence_graph.svg").exists()
        assert (root / "figures" / "non_review_evidence_graph.svg").exists()
        assert (root / "figures" / "topic_year_evolution.svg").exists()
        json.dumps(report)
