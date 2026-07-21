from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from literature_pipeline.claim_evidence_store import validate_store  # noqa: E402
from literature_pipeline.citation_verification import verify_manuscript  # noqa: E402
from literature_pipeline.deduplication import merge_versions  # noqa: E402
from literature_pipeline.document_parser import parse_document  # noqa: E402
from literature_pipeline.evidence_extraction import find_evidence_candidates  # noqa: E402
from literature_pipeline.schema import Paper  # noqa: E402
from literature_pipeline.screening import screen_papers  # noqa: E402


def paper(identifier: str, *, access: str, kind: str, doi: str = "", arxiv: str = "") -> Paper:
    return Paper(
        paper_id=identifier,
        work_id="",
        title="A Unified Method for Evidence Grounding",
        authors=["Jane Smith", "Alex Doe"],
        year=2024 if "journal" in identifier else 2023,
        source="Journal" if kind == "journal-article" else "arXiv",
        citation_key="smith2024",
        doi=doi,
        arxiv_id=arxiv,
        document_type=kind,
        access_level=access,
        existence_verified=True,
    )


class LiteraturePipelineTests(unittest.TestCase):
    def test_screening_uses_relevance_and_diversity_not_citations_alone(self) -> None:
        relevant = Paper("p1", "", "Retrieval augmented generation evaluation", ["A One"], 2024, abstract="A benchmark evaluation method and dataset.", citation_count=1, source="Venue A", document_type="journal-article")
        irrelevant = Paper("p2", "", "Cancer imaging study", ["B Two"], 2024, abstract="A highly cited medical model.", citation_count=10000, source="Venue B", document_type="journal-article")
        papers, report = screen_papers([irrelevant, relevant], query="retrieval augmented generation", target=2, min_relevance=0.2)
        decisions = {item.paper_id: item.screening_decision for item in papers}
        self.assertEqual(decisions["p1"], "included_rule_stage")
        self.assertEqual(decisions["p2"], "excluded")
        self.assertTrue(report["semantic_review_required"])

    def test_version_merge_keeps_formal_citation_and_readable_preprint(self) -> None:
        preprint = paper("preprint", access="fulltext", kind="preprint", arxiv="2401.01234v2")
        journal = paper("journal", access="abstract_only", kind="journal-article", doi="https://doi.org/10.1000/xyz")
        merged = merge_versions([preprint, journal])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].citation_version_paper_id, "journal")
        self.assertEqual(merged[0].read_version_paper_id, "preprint")
        self.assertEqual(merged[0].access_level, "fulltext")
        self.assertEqual(merged[0].citation_key, "smith2024")
        self.assertEqual(len(merged[0].versions), 2)

    def test_jats_parser_preserves_sections_paragraphs_and_tables(self) -> None:
        xml = """<article><body><sec><title>Methods</title><p>We trained the model.</p></sec><sec><title>Results</title><p>The score was 91.</p><table-wrap><label>Table 1</label><caption><p>Main results</p></caption><table><tr><td>91</td></tr></table></table-wrap></sec></body></article>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.xml"
            path.write_text(xml, encoding="utf-8")
            document = parse_document(path, paper_id="p1")
        self.assertEqual(document.access_level, "fulltext")
        self.assertEqual([item["title"] for item in document.sections], ["Methods", "Results"])
        self.assertTrue(any(block.table_id == "Table 1" for block in document.blocks))
        candidates = find_evidence_candidates(document.to_dict(), query="model score", sections=["Results"])
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0]["claim_supported"])

    def test_abstract_cannot_support_performance_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = paper("p1", access="abstract_only", kind="journal-article", doi="10.1000/xyz")
            (root / "papers.json").write_text(json.dumps({"papers": [p.to_dict()]}), encoding="utf-8")
            ledger = {
                "schema_version": "2.0",
                "claims": [{
                    "claim_id": "RQ1-C01", "text": "The model scored 91.", "claim_type": "performance_number",
                    "strength": "strong", "research_questions": ["RQ1"], "topics": ["evaluation"], "support_status": "verified",
                    "evidence": [{"evidence_id": "e1", "paper_id": "p1", "access_level": "abstract_only", "relation": "supports", "source_section": "Abstract", "excerpt": "score 91", "confidence": "high", "existence_verified": True, "claim_supported": True}],
                }],
            }
            (root / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            report = validate_store(root / "ledger.json", root / "papers.json")
        self.assertFalse(report["passed"])
        self.assertTrue(any("requires section_level" in error for error in report["errors"]))

    def test_located_section_evidence_can_support_performance_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = paper("p1", access="section_level", kind="journal-article", doi="10.1000/xyz")
            (root / "papers.json").write_text(json.dumps({"papers": [p.to_dict()]}), encoding="utf-8")
            ledger = {
                "schema_version": "2.0",
                "claims": [{
                    "claim_id": "RQ1-C01", "text": "The model scored 91.", "claim_type": "performance_number",
                    "strength": "strong", "research_questions": ["RQ1"], "topics": ["evaluation"], "support_status": "verified",
                    "evidence": [{"evidence_id": "e1", "paper_id": "p1", "access_level": "section_level", "relation": "supports", "source_section": "Results", "table_id": "Table 2", "excerpt": "score 91", "confidence": "high", "existence_verified": True, "claim_supported": True}],
                }],
            }
            (root / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            report = validate_store(root / "ledger.json", root / "papers.json")
        self.assertTrue(report["passed"], report["errors"])

    def test_citation_audit_links_sentence_key_number_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = paper("p1", access="section_level", kind="journal-article", doi="10.1000/xyz")
            (root / "papers.json").write_text(json.dumps({"papers": [p.to_dict()]}), encoding="utf-8")
            sentence = r"The model scored 91 in the reported evaluation \cite{smith2024}."
            (root / "review.tex").write_text(sentence, encoding="utf-8")
            ledger = {"schema_version": "2.0", "claims": [{
                "claim_id": "RQ1-C01", "text": "The model scored 91.", "manuscript_text": sentence,
                "citation_keys": ["smith2024"], "claim_type": "performance_number", "strength": "strong",
                "research_questions": ["RQ1"], "topics": ["evaluation"], "support_status": "verified",
                "evidence": [{"paper_id": "p1", "access_level": "section_level", "relation": "supports", "source_section": "Results", "table_id": "Table 2", "excerpt": "The model scored 91.", "confidence": "high", "existence_verified": True, "claim_supported": True}],
            }]}
            (root / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            report = verify_manuscript(root / "review.tex", root / "ledger.json", root / "papers.json")
        self.assertTrue(report["passed"], report["errors"])


if __name__ == "__main__":
    unittest.main()
