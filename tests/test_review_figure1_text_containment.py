from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_review_figure1 import DEFAULT_SPEC, run_pipeline  # noqa: E402


def test_flowchart_measures_text_with_migrated_design_system() -> None:
    legacy_spec = deepcopy(DEFAULT_SPEC)
    legacy_spec["layout"].update({"box_rx": 1, "panel_rx": 4, "stage_pill_rx": 18})
    svg, report = run_pipeline(legacy_spec)

    containment = report["final_layout"]["text_containment"]
    design_system = report["final_style"]["design_system"]
    assert svg.startswith("<svg")
    assert report["validation"]["passed"] is True
    assert report["validation"]["unified_design_system_applied"] is True
    assert containment["passed"] is True
    assert "Pillow/DejaVu Sans" in containment["measurement_engine"]
    assert all(item["horizontal_passed"] for item in containment["checks"])
    assert all(item["vertical_passed"] for item in containment["checks"])
    assert all(item["icon_clearance_passed"] for item in containment["checks"])
    assert not any(item["icon_column_reserved"] for item in containment["checks"])
    assert design_system["source_branch"] == "refactor/figure1-design-system"
    assert design_system["corner_radius_px"] == 10.0
    assert design_system["stroke_width_px"] == 1.5
    assert design_system["decorative_icons"] is False
    assert design_system["figure_title_position"] == "below diagram"
    assert 'stroke-dasharray="6 4"' in svg
    assert 'rx="4.0"' not in svg
    assert 'rx="18.0"' not in svg
