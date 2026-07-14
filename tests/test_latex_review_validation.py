from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_latex_review import validate_latex_review  # noqa: E402


def _write_passing_artifact(tmp_path: Path) -> Path:
    (tmp_path / "figure.png").write_bytes(b"not a real png, existence is enough")
    (tmp_path / "refs.bib").write_text(
        """
@article{smith2024,
  title={Review evidence},
  author={Smith, Jane},
  year={2024}
}
""",
        encoding="utf-8",
    )
    tex = tmp_path / "review.tex"
    tex.write_text(
        r"""
\documentclass{article}
\title{A Careful Review of Evidence}
\begin{document}
\maketitle
\begin{abstract}
This review summarizes the evidence base and explains the scope of the synthesis.
\end{abstract}
\keywords{evidence synthesis; literature review; validation}

\section{Introduction}
The introduction establishes the research context and cites prior work \cite{smith2024}.

\section{Dataset and methods}
The review searched databases, screened records, and extracted variables for synthesis.

\section{Results}
The results report thematic patterns across the included studies.

\begin{figure}
\includegraphics{figure.png}
\caption{Evidence map for included studies.}
\label{fig:evidence-map}
\end{figure}

\section{Discussion}
The discussion compares the findings with the existing research landscape.

\section{Conclusion}
The conclusion states implications for future research and practice.

\bibliography{refs}
\end{document}
""",
        encoding="utf-8",
    )
    return tex


class LatexReviewValidationTests(unittest.TestCase):
    def test_validate_latex_review_accepts_complete_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tex = _write_passing_artifact(Path(tmp))

            result = validate_latex_review(tex, min_words=40, min_figures=1).to_dict()

        self.assertTrue(result["passed"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["metrics"]["figure_count"], 1)
        self.assertEqual(result["metrics"]["citation_count"], 1)
        self.assertEqual(result["metrics"]["resolved_citation_count"], 1)
        self.assertEqual(result["metrics"]["required_sections"]["methods"], "dataset and methods")

    def test_validate_latex_review_reports_multiple_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tex = Path(tmp) / "broken.tex"
            tex.write_text(
                r"""
\documentclass{article}
\begin{document}
Prompt: write a better review.
```markdown
# Draft heading
```
\begin{abstract}
TODO add real abstract.
\end{abstract}
\section{Background}
This draft cites \cite{missing2025} and still contains [insert synthesis].
\section{Methodology}
Methods text.
\section{Findings}
Results text.
\begin{figure}
\includegraphics{missing-image.png}
\caption{A missing graphic without a label.}
\end{figure}
\end{document}
""",
                encoding="utf-8",
            )

            result = validate_latex_review(tex, min_words=200, min_figures=2).to_dict()

        self.assertFalse(result["passed"])
        errors = "\n".join(result["errors"])
        self.assertIn("Missing non-empty \\title", errors)
        self.assertIn("Missing keywords", errors)
        self.assertIn("Missing required discussion section", errors)
        self.assertIn("Missing required conclusion section", errors)
        self.assertIn("Markdown fenced code block marker", errors)
        self.assertIn("prompt trace label", errors)
        self.assertIn("unresolved placeholder token", errors)
        self.assertIn("bracketed placeholder", errors)
        self.assertIn("includegraphics path does not exist: missing-image.png", errors)
        self.assertIn("caption/label pairing issue", errors)
        self.assertIn("Citation key is unresolved: missing2025", errors)
        self.assertIn("Word count", errors)
        self.assertIn("Figure count", errors)

    def test_validate_latex_review_cli_writes_json_and_returns_nonzero_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex = tmp_path / "bad.tex"
            report = tmp_path / "report.json"
            tex.write_text(r"\documentclass{article}\begin{document}\end{document}", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "validate_latex_review.py"),
                    "--input",
                    str(tex),
                    "--report",
                    str(report),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 1)
            payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertFalse(payload["passed"])
        self.assertIn("errors", payload)
        self.assertIn("warnings", payload)
        self.assertIn("metrics", payload)

    def test_validate_latex_review_accepts_chinese_sections_and_counts_cjk_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex = tmp_path / "review.tex"
            tex.write_text(
                r"""
\documentclass{ctexart}
\title{人工智能教育研究综述}
\begin{document}
\maketitle
\begin{abstract}本文综合分析人工智能教育领域的研究进展与证据边界。\end{abstract}
\textbf{关键词：}人工智能教育；文献综述；主题演化
\section{引言}本节说明研究背景、问题范围与综述价值。
\section{数据来源与方法}本节说明文献检索、筛选与编码过程。
\section{结果}本节综合年度变化、研究主题与代表性证据。
\section{讨论}本节比较证据差异并回答研究问题。
\section{结论}本节总结主要发现、限制与未来方向。
\end{document}
""",
                encoding="utf-8",
            )

            result = validate_latex_review(tex, min_words=30).to_dict()

        self.assertTrue(result["passed"])
        self.assertGreater(result["metrics"]["cjk_character_count"], 50)
        self.assertGreaterEqual(result["metrics"]["word_count"], 30)

    def test_english_language_gate_accepts_english_manuscript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tex = _write_passing_artifact(Path(tmp))

            result = validate_latex_review(tex, language="english").to_dict()

        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["metrics"]["required_language"], "english")
        self.assertEqual(result["metrics"]["cjk_character_count"], 0)

    def test_english_language_gate_rejects_cjk_manuscript_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tex = _write_passing_artifact(Path(tmp))
            text = tex.read_text(encoding="utf-8").replace("Evidence map", "证据图")
            tex.write_text(text, encoding="utf-8")

            result = validate_latex_review(tex, language="english").to_dict()

        self.assertFalse(result["passed"])
        self.assertTrue(any("English-only output" in error for error in result["errors"]))
        self.assertGreater(result["metrics"]["cjk_character_count"], 0)

    def test_english_language_gate_rejects_cjk_in_svg_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = _write_passing_artifact(root)
            (root / "figure.svg").write_text("<svg><text>主题演化</text></svg>", encoding="utf-8")

            result = validate_latex_review(tex, language="english").to_dict()

        self.assertFalse(result["passed"])
        self.assertTrue(any("in figure source" in error for error in result["errors"]))
        self.assertEqual(len(result["metrics"]["non_english_figure_sources"]), 1)

    def test_validate_latex_review_checks_evidence_and_figure_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex = _write_passing_artifact(tmp_path)
            ledger = tmp_path / "evidence.json"
            ledger.write_text(
                json.dumps(
                    {
                        "claims": [
                            {
                                "claim_id": "RQ1-C01",
                                "claim": "The evidence base has a measurable publication trend.",
                                "sources": ["smith2024"],
                                "evidence": ["The included record reports the observed trend."],
                                "confidence": "high",
                                "limitations": "Single-record fixture.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            figure_report = tmp_path / "figure.report.json"
            figure_report.write_text(json.dumps({"validation": {"passed": True}}), encoding="utf-8")

            result = validate_latex_review(
                tex,
                evidence_ledger=ledger,
                required_rqs=("RQ1",),
                figure_reports=(figure_report,),
            ).to_dict()

        self.assertTrue(result["passed"])
        self.assertEqual(result["metrics"]["evidence_ledger"]["covered_rqs"], ["RQ1"])
        self.assertEqual(result["metrics"]["figure_reports"]["passed_report_count"], 1)


if __name__ == "__main__":
    unittest.main()
