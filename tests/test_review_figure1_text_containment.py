from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_review_figure1 import DEFAULT_SPEC, run_pipeline  # noqa: E402


def test_flowchart_measures_text_and_reserves_icon_columns() -> None:
    svg, report = run_pipeline(DEFAULT_SPEC)

    containment = report["final_layout"]["text_containment"]
    assert svg.startswith("<svg")
    assert report["validation"]["passed"] is True
    assert containment["passed"] is True
    assert "Pillow/DejaVu Sans" in containment["measurement_engine"]
    assert all(item["horizontal_passed"] for item in containment["checks"])
    assert all(item["vertical_passed"] for item in containment["checks"])
    assert all(item["icon_clearance_passed"] for item in containment["checks"])
    assert any(item["icon_column_reserved"] for item in containment["checks"])
