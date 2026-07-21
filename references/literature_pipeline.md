# Structured Literature Pipeline Contract

Use this contract between `literature_search` and `review_builder`. Persist failures and missing fields; never infer unavailable paper content.

## Pipeline

1. Retrieve 200–500 metadata candidates from at least two available APIs.
2. Normalize DOI/arXiv identifiers and merge duplicate/preprint/conference/journal versions under one `work_id`.
3. Select the formal publication as the citation version and the deepest openly readable version as the read version. Record both.
4. Screen titles and abstracts into an 80–120 paper material library using date, type, relevance, population, method transparency, source quality, classicity, recency, and diversity. Citation count is only one signal.
5. Plan claims before upgrading reading depth. Upgrade only the papers required by method, result, limitation, comparison, or consensus claims.
6. Parse open documents in this order: JATS/XML, structured HTML, LaTeX source, parseable PDF, OCR PDF. The first version implements JATS/XML, HTML, and parseable PDF; unsupported/OCR documents must remain explicitly unresolved.
7. Convert included papers to Paper Cards. Synthesize cards in theme/method/time batches of 15–25 papers.
8. Give the Writer only RQs, outline, Theme Syntheses, and verified Claim–Evidence records.
9. Run evidence permission validation before writing and citation verification after writing.

## Paper Store

Each paper must record:

- identity: `paper_id`, `work_id`, title, authors, year, source, DOI, arXiv ID, URL;
- discovery: abstract, keywords, topic tags, citations, open-access flag, retrieval sources;
- screening: decision and explicit inclusion/exclusion reasons;
- versions: all merged versions, citation version, actual read version;
- access: `access_level`, accessed sections/content, full-text source and format;
- policy: program-derived `allowed_claim_types`;
- verification: `existence_verified` and missing fields.

Never hand-edit `allowed_claim_types`; derive it from `access_level`.

## Access and Usage Matrix

| Level | Meaning | Permitted uses |
|---|---|---|
| `metadata_only` | Existence and bibliography verified only | existence, authors, year, source, publication statistics |
| `abstract_only` | Abstract reliably read | background, direction existence, stated RQ, coarse method, abstract-stated finding |
| `section_level` | Relevant named sections reliably parsed | method detail, experiments/results, located numbers, limitations, comparison, future directions |
| `fulltext` | Complete body parsed | all claim types, subject to locator and multi-paper requirements |

Detailed methods, performance numbers, ablations, limitations, causality, and consensus must not be inferred from metadata or abstracts. A performance number requires a table, page, or paragraph locator. A limitation requires Discussion/Limitations evidence. Field consensus requires at least three distinct papers.

## Claim–Evidence Store v2

Top level:

```json
{"schema_version":"2.0","claims":[]}
```

Each claim records `claim_id`, `text`, `claim_type`, `strength`, `research_questions`, `topics`, `support_status`, `limitations`, and one or more evidence objects. After drafting, also record the exact final `manuscript_text` sentence and its `citation_keys` for deterministic citation placement and number auditing. Each evidence object records:

```json
{
  "evidence_id": "EV-001",
  "paper_id": "paper-...",
  "access_level": "section_level",
  "source_section": "Results",
  "page": 7,
  "paragraph_id": "p-42",
  "table_id": "Table 2",
  "excerpt": "A short, copyright-safe supporting excerpt or faithful local summary.",
  "relation": "supports",
  "confidence": "high",
  "existence_verified": true,
  "claim_supported": true
}
```

Keep `existence_verified` separate from `claim_supported`. Index APIs can establish the former, never the latter.

## FulltextDocument

Persist source URL/format, parser, access level, completeness, warnings, named sections, and ordered blocks. Each block records kind, text, section, page/paragraph locator, table ID, and caption when available.

## Paper Card and Theme Synthesis

A Paper Card records RQs, methods, datasets, baselines, results, limitations, innovations, topics, access level, evidence IDs, and unresolved fields. Do not fill a field without permitted evidence.

A Theme Synthesis records consensus, disagreements, method evolution, representative papers, evidence strength, gaps, open questions, and linked `claim_id` values. It may summarize verified cards but must not create unsupported paper facts.
