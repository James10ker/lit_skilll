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
