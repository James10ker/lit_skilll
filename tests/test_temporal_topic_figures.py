from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_temporal_topic_figures import load_records, run_pipeline  # noqa: E402


def test_temporal_topic_pipeline_renders_two_valid_figures() -> None:
    records, warnings = load_records(ROOT / "tools" / "examples" / "aied_bibliometric_network_records.json")
    figures, report = run_pipeline(
        records,
        start_year=2015,
        end_year=2024,
        window_years=5,
        max_topics=24,
        annual_title="Figure 3. Year-by-year number of AIEd publications",
        topic_title="Figure 4. AIEd research topics in two periods",
        warnings=warnings,
    )

    assert figures["annual_publications"].startswith("<svg")
    assert BAR_COLOR_IN_SVG in figures["annual_publications"]
    assert "Polynomial trend" in figures["annual_publications"]
    assert figures["topic_wordcloud"].startswith("<svg")
    assert "2015-2019" in figures["topic_wordcloud"]
    assert "2020-2024" in figures["topic_wordcloud"]
    assert report["validation"]["passed"] is True
    assert report["wordcloud_checks"]["word_overlaps"] == []
    assert report["topic_windows"]["earlier"]["record_count"] > 0
    assert report["topic_windows"]["recent"]["record_count"] > 0
    json.dumps(report, ensure_ascii=False)


def test_temporal_topic_pipeline_fails_when_a_window_has_no_topic_data() -> None:
    records, _ = load_records(ROOT / "tools" / "examples" / "aied_bibliometric_network_records.json")
    _, report = run_pipeline(
        records,
        start_year=2019,
        end_year=2030,
        window_years=5,
        max_topics=20,
        annual_title="Annual",
        topic_title="Topics",
    )

    assert report["validation"]["passed"] is False
    assert report["validation"]["recent_window_has_records"] is False


BAR_COLOR_IN_SVG = "#b2221b"
