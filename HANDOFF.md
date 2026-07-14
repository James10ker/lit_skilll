# Literature Review Skill Handoff

Last updated: 2026-07-14 (Asia/Shanghai)

## 1. Current State

- Repository: `https://github.com/James10ker/lit_skilll`
- Branch: `main`
- Remote HEAD: `1d38358`
- Working tree at handoff: clean
- Claude Code skill link on the old machine:
  `/home/james/.claude/skills/literature-review-skill -> /home/james/lit_skilll`
- Latest generated review on the old machine:
  `/home/james/lit_skilll/outputs/aied_cc_trial_en_v2/review.pdf`

Critical migration warning: `.gitignore` excludes the complete `outputs/`
directory. A normal `git clone` restores the skill and renderers, but it does
not restore the 150-record corpus, generated figures, reports, LaTeX source, or
PDF. Transfer the required output directories separately before continuing.

Recommended data transfer set:

```text
outputs/aied_cc_trial/
outputs/aied_cc_trial_en_v2/
```

Example from the old machine:

```bash
tar -czf lit_skill_outputs_handoff.tar.gz \
  outputs/aied_cc_trial \
  outputs/aied_cc_trial_en_v2
```

After cloning on the new machine, extract the archive at the repository root.

## 2. User's Active Requirement

The latest English review currently contains only three figures. The user has
required the figure set to follow Tasks 2, 3, and 4 in:

```text
docs/基于agent的研究综述自动生成计划书(1).docx
```

Relevant plan text:

- Task 2: generate two graphs, with six node types and six edge types, split
  into review and non-review literature.
- Task 3: generate and use the literature collection/screening flowchart.
- Task 4: generate a topic word cloud comparing the latest complete five-year
  window with the preceding five-year window.
- The same task block also calls for annual publication counts, topic-year
  evolution, author-topic, paper-citation, and author-journal relationships.

Do not reduce this requirement back to a three-figure default. The intended
minimum for the current review is six figures:

1. Literature search and screening flowchart.
2. Annual publication trend.
3. Two-window topic word cloud.
4. Review-literature six-node relationship graph.
5. Non-review-literature six-node relationship graph.
6. Topic-year annual evolution heatmap.

The two relationship graphs cover the other Task 4 relationships, so separate
author-topic, paper-citation, and author-journal figures are not required unless
the user asks for each relation as an independent figure.

## 3. Plan Task 2 Graph Contract

The implementation uses these six named node types:

```text
journal, author, topic, year, paper, citation
```

It uses these six edge types:

```text
author-journal
author-topic
topic-year
year-paper
paper-topic
paper-citation
```

The graph is split into two outputs using title/work-type classification:

- review literature
- non-review literature

Every visible label is English. Labels are wrapped and stacked inside their
nodes. Empty/placeholder labels are excluded. The validation report must show:

```json
{
  "passed": true,
  "two_graphs_rendered": true,
  "six_node_types_per_graph": true,
  "six_edge_types_per_graph": true,
  "no_unnamed_nodes": true,
  "no_node_overlaps": true,
  "topic_year_rendered": true
}
```

Do not describe these heterogeneous evidence graphs as country or institution
collaboration networks. The current corpus lacks affiliation and country data.

## 4. Work Completed

### Skill and English quality gates

Commit `8c6d8a1` contains the all-English review workflow and quality-gate work.
The skill now requires English for the title, abstract, keywords, body, tables,
captions, notes, axes, legends, and node labels. The LaTeX validator supports:

```bash
python3 tools/validate_latex_review.py \
  --input path/to/review.tex \
  --report path/to/latex_quality.report.json \
  --language english
```

The validator checks CJK characters in the `.tex` manuscript and in same-stem
SVG sources referenced through PNG/SVG figures.

Other enforced rules include:

- latest five-year windows end at the latest complete year;
- topic codes and display labels must be canonicalized;
- primary and secondary topic counting must use a declared, consistent basis;
- evidence claims must match full-text/abstract/metadata coverage;
- manuscript RQs, evidence-ledger RQs, and figure-plan RQs must match.

### Plan Tasks 2 and 4 renderer

Commit `1d38358` is on `origin/main` and adds:

```text
tools/render_plan_task_figures.py
tests/test_plan_task_figures.py
```

The renderer generates:

```text
review_evidence_graph.svg/png
non_review_evidence_graph.svg/png
topic_year_evolution.svg/png
```

Generation command used on the old machine:

```bash
python3 tools/render_plan_task_figures.py \
  --input outputs/aied_cc_trial_en_v2/data/prepared_records.json \
  --output-dir outputs/aied_cc_trial_en_v2/figures \
  --report outputs/aied_cc_trial_en_v2/reports/figure_plan_tasks_2_4.report.json \
  --start-year 2015 \
  --end-year 2024
```

Observed report summary on the old machine:

```text
input records usable by Task 2: 131
review records: 20
non-review records: 111
validation.passed: true
all six node types present: true
all six edge types present: true
unnamed nodes: 0
node overlaps: 0
topic-year chart rendered: true
```

The original corpus has 150 records. Nineteen records lack one or more fields
required by the relationship graph and are excluded only from Task 2 graphs;
they remain in publication and topic analyses.

## 5. Work Still Required

The three new figures were rendered and visually inspected, but the previous
turn was interrupted before they were integrated into `review.tex`. Therefore,
the current `review.pdf` still has only the original three figures.

Continue in this order:

1. Restore `outputs/aied_cc_trial_en_v2/` on the new machine.
2. Re-run `render_plan_task_figures.py` to make paths and reports local to the
   new environment.
3. Edit `outputs/aied_cc_trial_en_v2/review.tex`:
   - add the review and non-review relationship graphs in the RQ2 results;
   - explain that they encode evidence relationships, not geographic or
     institutional collaboration;
   - add the topic-year heatmap in the RQ3 temporal-results section;
   - state that 19 records were omitted from Task 2 because required graph
     fields were incomplete;
   - cite and interpret every new figure in the surrounding prose.
4. Ensure the final document contains at least six `figure` environments.
5. Add `figure_plan_tasks_2_4.report.json` to the LaTeX validation command.
6. Compile a new PDF if a LaTeX engine is available.
7. Render PDF pages to PNG and visually verify all six figures.
8. Update the skill documentation so future plan-driven AIEd generations use
   this six-figure minimum rather than the current three-figure wording.

Suggested LaTeX figure blocks:

```latex
\begin{figure}[H]
  \centering
  \includegraphics[width=\textwidth]{figures/review_evidence_graph.png}
  \caption{Evidence relationships among review publications. The graph links
  journals, authors, topics, years, papers, and citation bands.}
  \label{fig:review-evidence-graph}
\end{figure}

\begin{figure}[H]
  \centering
  \includegraphics[width=\textwidth]{figures/non_review_evidence_graph.png}
  \caption{Evidence relationships among non-review publications using the
  same six node and edge categories.}
  \label{fig:non-review-evidence-graph}
\end{figure}

\begin{figure}[H]
  \centering
  \includegraphics[width=\textwidth]{figures/topic_year_evolution.png}
  \caption{Annual primary-topic intensity from 2015 to 2024. Cell values are
  topic shares within each publication year.}
  \label{fig:topic-year-evolution}
\end{figure}
```

## 6. Validation Commands

Install/runtime requirements:

- Python 3.11+ (old environment used Python 3.14.4)
- `rsvg-convert` for SVG-to-PNG output
- a LaTeX engine such as `latexmk` plus `pdflatex`/`xelatex` for PDF rebuild
- Poppler (`pdfinfo`, `pdftoppm`, `pdftotext`) for PDF inspection

The old environment had Python, `rsvg-convert`, and Poppler, but no LaTeX
engine on `PATH` at the handoff check.

Run focused tests:

```bash
python3 -m unittest tests.test_latex_review_validation
python3 tests/test_temporal_topic_figures.py
python3 tests/test_bibliometric_network_render.py
python3 tests/test_math_render.py
python3 tests/test_plan_task_figures.py
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
python3 -m py_compile tools/*.py
git diff --check
```

Known unrelated test gap: full `unittest discover` currently fails while
collecting `tests/test_md_to_docx_table.py` because `tools/md_to_docx.py` is not
present. This is unrelated to the LaTeX and plan-figure workflow.

After integrating all figures, run a command shaped like:

```bash
python3 tools/validate_latex_review.py \
  --input outputs/aied_cc_trial_en_v2/review.tex \
  --report outputs/aied_cc_trial_en_v2/reports/latex_quality.report.json \
  --language english \
  --evidence-ledger outputs/aied_cc_trial_en_v2/data/evidence_ledger.json \
  --required-rqs RQ1,RQ2,RQ3,RQ4 \
  --figure-report outputs/aied_cc_trial_en_v2/reports/figure_flow.report.json \
  --figure-report outputs/aied_cc_trial_en_v2/reports/figure_temporal.report.json \
  --figure-report outputs/aied_cc_trial_en_v2/reports/figure_plan_tasks_2_4.report.json \
  --min-words 3000 \
  --min-figures 6
```

Confirm that the RQ list above still matches the actual manuscript before
running it. Do not mechanically retain RQ identifiers if the new environment
regenerates the review with a different RQ set.

## 7. Skill Contract Update Still Needed

The current committed skill documentation still contains language that makes
three figures the reference-review default. Replace that with a plan-specific
contract:

- When the user invokes the AIEd plan/Tasks 2-4, six figures are mandatory.
- Two Task 2 graphs must always be attempted from author, paper, topic, year,
  journal, citation, and work-type fields.
- Missing affiliations/countries prevent geographic collaboration claims but
  do not cancel the two Task 2 evidence graphs.
- Task 4 requires both the two-window word cloud and topic-year evolution.
- `--min-figures 6` applies to this plan workflow.
- Every generated figure report must be supplied to the final validator.

Likely files to edit:

```text
SKILL.md
README.md
prompts/reference_review_synthesis.md
prompts/figure_table_handling.md
prompts/review_builder.md
prompts/review_self_check.md
prompts/latex_delivery.md
```

## 8. Visual and Evidence Constraints

- Final paper and all figures must be entirely English.
- No unnamed nodes.
- Node labels must be wrapped/stacked inside the node.
- Text must not overlap other text or neighboring nodes.
- Nodes must not overlap.
- Use 2015-2019 and 2020-2024 for the two complete five-year windows.
- Treat 2025 as incomplete and exclude it from five-year comparisons.
- Keep topic codes separate from English display labels; never count both.
- Only 31 of the 150 records have local full text. Do not describe the complete
  corpus as a full-text synthesis.
- Do not claim country/institution collaboration without affiliation/country
  data.
- The two relationship graphs are sampled/ranked views for readability; report
  that fact and preserve the machine-readable report.

## 9. Recommended First Prompt in the New Environment

```text
Read HANDOFF.md and continue the interrupted AIEd plan Tasks 2-4 work. Restore
or verify outputs/aied_cc_trial_en_v2, regenerate the two six-node relationship
graphs and the topic-year chart, integrate all three into review.tex, rebuild
the PDF, and validate a minimum of six English figures. Do not stop at a plan.
Use the report and validation commands in HANDOFF.md, and keep country or
institution collaboration claims out because those fields are unavailable.
```

