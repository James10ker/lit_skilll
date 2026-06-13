# Tools

本目录保留论文综述写作中常用的格式转换和图示渲染工具。

## Office 转 Markdown

```bash
python3 tools/docx_to_md.py --input path/to/file.docx --output path/to/file.md
python3 tools/pptx_to_md.py --input path/to/file.pptx --output path/to/file.md
```

用于在扫描资料前提取 Word / PowerPoint 内容。图片默认导出到同级媒体目录。

## Markdown 转 Word

```bash
python3 tools/md_to_docx.py --input path/to/review.md --output path/to/review.docx
```

用于把最终综述交付为可继续修订的 `.docx`。

## Mermaid 渲染

```bash
python3 tools/mermaid_render.py -i path/to/review.md -o path/to/review_rendered.md
```

将 Markdown 中的 fenced `mermaid` 图渲染为 PNG，便于嵌入 Word。适合分类框架图、研究路线图、方法谱系图和时间线。

## 综述 Figure 1 专用流程图

```bash
python3 tools/render_review_figure1.py \
  --spec tools/examples/aied_figure1_spec.json \
  --output outputs/figures/aied_figure1.svg
```

用于生成接近示例综述 Figure 1 的“文献收集与分析流程图”。脚本现在内建一条稳定流水线：

`Graph IR -> 逻辑校验 -> 初次渲染 -> 布局质量评估 -> SVG bbox 检查 -> Graphviz JSON 坐标检查 -> PNG 边缘像素检查 -> 自动重排/加约束 -> 再次渲染 -> 可读性检查 -> 最终输出`

这意味着大模型不是“直接画”，而是先产出结构化 spec，再由脚本完成拓扑检查和版式兜底。

输出：

- `*.svg`：可直接嵌入 Markdown、Word、网页或后续转 PNG。

建议流程：

1. 大模型先生成一份 JSON spec。
2. 用 `python3 tools/render_review_figure1.py --output ... --report ...` 出图并落盘评估报告。
3. 若只是换数字、数据库名或排除理由，只改 JSON，不改脚本。

常用命令：

```bash
python3 tools/render_review_figure1.py --dump-template
python3 tools/render_review_figure1.py --spec tools/examples/aied_figure1_spec.json --dump-ir
python3 tools/render_review_figure1.py --spec tools/examples/aied_figure1_spec.json --validate-only --report outputs/figures/aied_figure1.report.json
python3 tools/render_review_figure1.py --spec tools/examples/aied_figure1_spec.json --output outputs/figures/aied_figure1.svg --report outputs/figures/aied_figure1.report.json
```

如需控制哪些连线带箭头，可在 spec 中填写：

```json
"connector_styles": {
  "strategy_one_to_total": "arrow",
  "strategy_two_to_total": "arrow",
  "total_to_manual": "arrow",
  "total_to_duplicate": "arrow",
  "manual_to_excluded": "arrow",
  "manual_to_analysis": "arrow",
  "analysis_to_citation": "arrow",
  "analysis_panel_arrow": "arrow"
}
```

值可用 `arrow` 或 `line`。这让大模型不仅能填内容，也能明确声明某条边是“流程箭头”还是“无方向辅助线”。

`--dump-ir` 可直接输出 Graph IR，便于后面让大模型先生成节点/边语义，再映射为图。

`--report` 会记录：

- 布局评分与重叠/溢出检查
- `SVG bbox` 边界留白检查
- `Graphviz JSON` 坐标与相对顺序检查
- `PNG` 边缘墨迹像素检查
- 是否触发了自动修复重渲染

## PDF 图表抽取

```bash
python3 tools/pdf_extract_figures.py --input path/to/paper.pdf --output-dir extracted/paper
python3 tools/pdf_extract_figures.py --input path/to/paper.pdf --output-dir extracted/paper --render-pages
```

输出：

- `figures/`：PDF 中可抽取的图片对象。
- `pages/`：使用 `--render-pages` 时输出整页 PNG，便于人工定位图表。
- `captions.md`：疑似 Figure/Table 图题和页码。
- `manifest.json`：抽取清单。

这些文件默认用于辅助阅读和重绘。综述正文应优先使用原创图、重绘图或根据多篇文献整理的对比表，不默认复制论文原图。

无本地 PDF 时，先下载开放获取 PDF：

```bash
mkdir -p outputs/topic/papers
curl -L "https://arxiv.org/pdf/xxxx.xxxxx" -o outputs/topic/papers/paper.pdf
python3 tools/pdf_extract_figures.py --input outputs/topic/papers/paper.pdf --output-dir outputs/topic/extracted/paper --render-pages
```

不要尝试绕过登录、验证码、付费墙或站点访问限制。下载失败时，在综述交付说明中记录失败原因。

## 综述参考文献元数据爬取

```bash
python3 tools/crawl_review_references.py \
  --input path/to/review.pdf \
  --output-dir outputs/review_reference_crawl
```

脚本会从综述 PDF 中抽取参考文献条目，并通过 Crossref、OpenAlex、Semantic Scholar 等公开元数据接口补充题名、年份、DOI、URL 和开放 PDF 链接。输出：

- `references.csv`：便于后续筛选、统计和人工核验。
- `references.json`：保留完整结构化结果。
- `references.md`：快速预览表。

如需尝试下载公开 PDF，可加：

```bash
python3 tools/crawl_review_references.py \
  --input path/to/review.pdf \
  --output-dir outputs/review_reference_crawl \
  --download-open-pdf
```

该选项只下载参考文献中已有的公开 PDF URL 或公共元数据接口暴露的开放 PDF，不绕过登录、验证码或付费墙。

## 修订记录

`iteration_dialog_log.py` 可作为通用追加日志工具使用。论文综述场景建议日志名为：

`综述修订记录.md`
