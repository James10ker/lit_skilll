# Review Flow Figure Plugin

本文说明当前仓库中的综述流程图生成能力，包括技术实现、JSON 输入格式、质量检查机制，以及如何在 CC（Claude Code）中作为 skill 插件使用和测试。

## 1. 模块定位

流程图生成模块的核心脚本是：

```text
tools/render_review_figure1.py
```

它不是通用 Mermaid 或任意 DAG 流程图渲染器，而是一个固定视觉语言的综述 Figure 1 渲染器，用于生成“文献检索、筛选、纳入分析、右侧分析步骤”的流程图。典型结构是：

```text
two search strategies
  -> total retrieved publications
  -> manual screening
  -> publications included for data analysis
  -> right-side analysis panel
```

同时带有三个辅助分支：

```text
duplicate exclusion
excluded publications
citation collection
```

上层 skill 规则位于：

```text
SKILL.md
prompts/figure_table_handling.md
```

这些规则强调：图表必须基于本次文献集合的统计结果或主题分析结果生成，不复制参考论文原图，不编造统计数据。

## 2. 输入输出

### 输入

输入是一个 JSON spec。示例文件：

```text
tools/examples/aied_figure1_spec.json
tools/examples/medical_education_figure2_spec.json
```

最小推荐结构：

```json
{
  "title": "Figure X. Data collection and analyses",
  "stage_labels": ["Identification", "Screening", "Included"],
  "left_caption": "Data collection and filtering",
  "right_caption": "Data analysis: publication trends, source distribution, collaboration patterns, topic evolution, and citation structure",
  "strategy_boxes": [
    {
      "text": "Strategy one (database search):\nWeb of Science, PubMed, and Scopus\n(N=18426)"
    },
    {
      "text": "Strategy two (additional search):\npublications in selected journals and conference proceedings\n(N=864)"
    }
  ],
  "total_box": "Total publications retrieved from database search and additional search\n(N=19290)",
  "duplicate_label": "Duplicated publication exclusion",
  "manual_box": "Publications included for manual screening and filtering\n(N=9320)",
  "excluded_box": "9970 publications were excluded:\n1) not related to the target domain;\n2) no use of AI;\n3) review, editorial, or commentary papers without concrete scenarios",
  "analysis_box": "Publications included for data analysis\n(N=4552)",
  "citation_box": "Collect the number of citations received by each publication in Google Scholar",
  "analysis_steps": [
    "Trend analysis of annual publications",
    "Identification of leading journals, countries/regions, and institutions",
    "Visualization of the scientific collaboration",
    "Topic identification, research hotspots, and trend analyses"
  ],
  "connector_styles": {
    "strategy_one_to_total": "arrow",
    "strategy_two_to_total": "arrow",
    "total_to_manual": "arrow",
    "total_to_duplicate": "line",
    "manual_to_excluded": "line",
    "manual_to_analysis": "arrow",
    "analysis_to_citation": "line",
    "analysis_panel_arrow": "arrow"
  }
}
```

### 输出

脚本输出 SVG，并可额外输出 JSON report：

```text
outputs/figures/<topic>_figure.svg
outputs/figures/<topic>_figure.report.json
```

PNG 不是脚本的正式输出参数，但可以用 `rsvg-convert` 从 SVG 转出：

```bash
rsvg-convert -o outputs/figures/<topic>_figure.png outputs/figures/<topic>_figure.svg
```

## 3. 技术流水线

`tools/render_review_figure1.py` 的稳定流水线是：

```text
JSON spec
-> merge with DEFAULT_SPEC
-> Graph IR
-> logical validation
-> first layout
-> first SVG render
-> layout quality assessment
-> post-render checks
-> optional relayout
-> second SVG render
-> final report
```

关键函数：

```text
load_spec()                合并用户 spec 与 DEFAULT_SPEC
build_ir()                 将 spec 转成固定节点和边
validate_ir()              校验节点、阶段、边和连接线样式
plan_layout()              计算固定 Figure 1 布局
assess_layout()            评估可读性、重叠、对齐、间距和画布利用率
maybe_relayout()           首次布局未通过时执行一次保守重排
render_svg()               生成最终 SVG 字符串
run_post_render_checks()   执行 SVG bbox、Graphviz JSON 坐标和 PNG 边缘像素检查
run_pipeline()             串起完整渲染与验证流程
```

## 4. Graph IR 约束

当前渲染器固定为 Figure 1 版式，因此 schema 有明确限制：

- `stage_labels` 必须正好 3 个，通常为 `Identification`、`Screening`、`Included`。
- `strategy_boxes` 必须正好 2 个。
- `analysis_steps` 必须正好 4 个。
- 连接线样式只能是 `arrow` 或 `line`。
- 固定边包括：

```text
strategy_one_to_total
strategy_two_to_total
total_to_manual
total_to_duplicate
manual_to_excluded
manual_to_analysis
analysis_to_citation
analysis_panel_arrow
```

如果需要任意数量节点、自由布局、多泳道或 Mermaid 语法，应新增另一个渲染器，而不是强行扩展这个 Figure 1 模块。

## 5. 布局与视觉规则

模块采用固定两栏布局：

- 左侧面板：文献收集、去重、人工筛选、纳入分析。
- 右侧面板：四个数据分析步骤。
- 中间大箭头：从纳入分析框指向右侧分析面板。

脚本内置检查包括：

- box 文本是否溢出。
- box 之间是否重叠。
- 主干节点是否对齐。
- 左右面板间距是否在合理范围内。
- 大箭头长度是否过长。
- 内容是否贴近 SVG/PNG 边缘。
- 图中实际节点坐标是否符合 Graphviz-style JSON 坐标约束。

如果首次布局失败，脚本会执行一次保守 `relayout`，微调左面板、右面板和部分 box 尺寸。

## 6. 本地依赖

基础运行依赖 Python 3 标准库。后渲染 PNG 边缘检查依赖 `rsvg-convert`：

```bash
rsvg-convert --version
```

如果缺失，在 Debian/Ubuntu 环境通常可安装：

```bash
sudo apt-get update
sudo apt-get install -y librsvg2-bin
```

仓库的 Python 依赖安装：

```bash
pip install -r requirements.txt
```

注意：`requirements.txt` 主要服务于文档转换、数学公式和其他图表处理；该流程图脚本本身主要依赖标准库和系统命令 `rsvg-convert`。

## 7. 命令行使用

查看内置模板：

```bash
python3 tools/render_review_figure1.py --dump-template
```

查看 Graph IR：

```bash
python3 tools/render_review_figure1.py \
  --spec tools/examples/medical_education_figure2_spec.json \
  --dump-ir
```

只验证，不写 SVG：

```bash
python3 tools/render_review_figure1.py \
  --spec tools/examples/medical_education_figure2_spec.json \
  --validate-only \
  --report outputs/figures/medical_education_figure2.report.json
```

生成 SVG 和 report：

```bash
mkdir -p outputs/figures

python3 tools/render_review_figure1.py \
  --spec tools/examples/medical_education_figure2_spec.json \
  --output outputs/figures/medical_education_figure2.svg \
  --report outputs/figures/medical_education_figure2.report.json
```

转 PNG：

```bash
rsvg-convert \
  -o outputs/figures/medical_education_figure2.png \
  outputs/figures/medical_education_figure2.svg
```

## 8. Report 检查方法

生成 report 后，应重点检查以下字段：

```text
logic_validation.passed
final_layout.readability_passed
final_layout.inter_panel_gap.passed
final_layout.connector_arrow_length.passed
final_layout.canvas_utilization.passed
final_layout.panel_layout_contract.passed
final_post_render.svg_bbox_passed
final_post_render.graphviz_json_passed
final_post_render.png_edge_passed
```

可以用一段 Python 快速检查：

```bash
python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("outputs/figures/medical_education_figure2.report.json").read_text())
checks = {
    "logic_validation": report["logic_validation"]["passed"],
    "readability": report["final_layout"]["readability_passed"],
    "inter_panel_gap": report["final_layout"]["inter_panel_gap"]["passed"],
    "connector_arrow_length": report["final_layout"]["connector_arrow_length"]["passed"],
    "canvas_utilization": report["final_layout"]["canvas_utilization"]["passed"],
    "panel_layout_contract": report["final_layout"]["panel_layout_contract"]["passed"],
    "svg_bbox": report["final_post_render"]["svg_bbox_passed"],
    "graphviz_json": report["final_post_render"]["graphviz_json_passed"],
    "png_edge": report["final_post_render"]["png_edge_passed"],
}
for name, passed in checks.items():
    print(f"{name}: {'PASS' if passed else 'FAIL'}")

raise SystemExit(0 if all(checks.values()) else 1)
PY
```

## 9. 在 CC 中使用这个插件

本文中的 CC 指 Claude Code。这个仓库本身是一个 skill 插件目录，根目录有 `SKILL.md`。要让 CC 使用它，确保目录位于 Claude Code 可发现的 skills 路径中。

项目级安装示例：

```bash
mkdir -p .claude/skills
cp -a /home/james/lit_skilll .claude/skills/literature-review-skill
```

用户级安装示例：

```bash
mkdir -p ~/.claude/skills
cp -a /home/james/lit_skilll ~/.claude/skills/literature-review-skill
```

安装后，在 CC 里可以这样调用：

```text
使用 literature-review-skill。请基于 Artificial Intelligence in Medical Education 生成综述 Figure 1 流程图：
1. 按 tools/render_review_figure1.py 的 schema 创建 JSON spec；
2. 保存到 tools/examples/medical_education_figure2_spec.json；
3. 渲染 SVG 到 outputs/figures/medical_education_figure2.svg；
4. 输出 report 到 outputs/figures/medical_education_figure2.report.json；
5. 用 rsvg-convert 转 PNG；
6. 检查 report 中 readability、inter_panel_gap、connector_arrow_length、canvas_utilization、panel_layout_contract 和 post-render checks 是否通过。
```

如果 CC 环境支持显式 skill 名称，也可以更直接地写：

```text
使用 review-flow-figure。请为主题 <TOPIC> 生成一个综述数据收集与分析流程图，输出 SVG、PNG 和 report，并报告验证结果。
```

生成 spec 时，建议让 CC 输出 JSON 文件，而不是让模型直接画图。推荐提示词：

```text
Generate only a JSON object for a review-style Figure 1 workflow diagram.

Task:
- Topic: <TOPIC>
- Figure style: literature collection and analysis flow diagram
- Output fields must exactly be:
  title, stage_labels, left_caption, right_caption, strategy_boxes,
  total_box, duplicate_label, manual_box, excluded_box,
  analysis_box, citation_box, analysis_steps, connector_styles

Rules:
- Keep stage_labels as ["Identification", "Screening", "Included"].
- Use English text in the boxes.
- Keep the visual logic as:
  two source boxes -> total box -> manual screening -> data analysis,
  with side branches for duplicated publication exclusion, excluded publications,
  and citation collection, plus a right-side analysis panel with four analysis steps.
- If no real statistics are provided, use clearly illustrative counts that are internally consistent.
- Return JSON only, no markdown fence, no explanation.
```

## 10. CC 测试教程

在 CC 中完成一次端到端测试，可以按下面流程执行。

### Step 1: 检查脚本和依赖

```bash
test -f tools/render_review_figure1.py
python3 --version
rsvg-convert --version
```

### Step 2: 运行默认模板验证

```bash
mkdir -p outputs/figures

python3 tools/render_review_figure1.py \
  --validate-only \
  --report outputs/figures/default_figure.report.json
```

预期输出：

```text
VALID=ok
```

### Step 3: 渲染示例 SVG

```bash
python3 tools/render_review_figure1.py \
  --spec tools/examples/medical_education_figure2_spec.json \
  --output outputs/figures/medical_education_figure2.svg \
  --report outputs/figures/medical_education_figure2.report.json
```

预期输出类似：

```text
OUTPUT=/absolute/path/to/outputs/figures/medical_education_figure2.svg
```

### Step 4: 转 PNG

```bash
rsvg-convert \
  -o outputs/figures/medical_education_figure2.png \
  outputs/figures/medical_education_figure2.svg
```

### Step 5: 自动检查 report

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("outputs/figures/medical_education_figure2.report.json")
report = json.loads(path.read_text())

checks = [
    ("logic_validation", report["logic_validation"]["passed"]),
    ("readability", report["final_layout"]["readability_passed"]),
    ("inter_panel_gap", report["final_layout"]["inter_panel_gap"]["passed"]),
    ("connector_arrow_length", report["final_layout"]["connector_arrow_length"]["passed"]),
    ("canvas_utilization", report["final_layout"]["canvas_utilization"]["passed"]),
    ("panel_layout_contract", report["final_layout"]["panel_layout_contract"]["passed"]),
    ("svg_bbox", report["final_post_render"]["svg_bbox_passed"]),
    ("graphviz_json", report["final_post_render"]["graphviz_json_passed"]),
    ("png_edge", report["final_post_render"]["png_edge_passed"]),
]

for name, passed in checks:
    print(f"{name}: {'PASS' if passed else 'FAIL'}")

if not all(passed for _, passed in checks):
    raise SystemExit(1)
PY
```

全部为 `PASS` 时，说明命令行渲染、布局检查和后渲染检查都通过。

### Step 6: 人工快速检查

打开生成的 PNG 或 SVG，确认：

- 主干方向清晰：检索策略 -> 总量 -> 人工筛选 -> 纳入分析。
- 右侧分析面板可读。
- 没有文本被截断。
- 箭头和辅助线没有丢失。
- 图注、统计数量和当前文献集合一致。

## 11. 常见问题

### `rsvg-convert` 不存在

安装 `librsvg2-bin`，或先只输出 SVG。注意：当前脚本的 post-render PNG 边缘检查需要 `rsvg-convert`，所以完整验证仍然需要它。

### 文本溢出或 report 失败

优先改 spec：

- 给长文本手动加 `\n`。
- 缩短排除理由。
- 保持 `analysis_steps` 简短。
- 不要把完整检索式塞进 box。

只有在多个合理 spec 都失败时，才考虑修改 `plan_layout()` 或 `fit_box()`。

### 需要更多检索策略或更多分析步骤

当前模块不支持。它的 IR 和布局都固定为 2 个 strategy box 和 4 个 analysis steps。若需要更自由的结构，建议新增独立渲染模块。

### 没有真实统计数量

可以生成演示图，但必须明确标注为 illustrative/example counts。正式综述图表不得把示例数包装成真实检索结果。

## 12. 维护建议

- 保持 `tools/examples/*.json` 与脚本 schema 同步。
- 修改布局逻辑后，至少运行：

```bash
python3 tools/render_review_figure1.py --validate-only --report outputs/figures/default_figure.report.json

python3 tools/render_review_figure1.py \
  --spec tools/examples/medical_education_figure2_spec.json \
  --output outputs/figures/medical_education_figure2.svg \
  --report outputs/figures/medical_education_figure2.report.json
```

- 检查 report 中所有关键字段。
- 人工查看 PNG，确认视觉上没有缺线、缺箭头或文本拥挤。
