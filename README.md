# 论文综述撰写 Skill

从论文、笔记、旧稿和检索结果出发，辅助完成文献综述写作；也支持按给定参考综述的数据来源、研究问题和图表类型进行复现式合成。效果对比用于复现实验或系统评测，不是每篇综述正文的必备章节。

## 能力

| 能力 | 说明 |
|------|------|
| 任务澄清 | 明确综述主题、类型、范围、篇幅、引用格式和交付形式 |
| 资料扫描 | 读取本地论文、Word、PPT、笔记、BibTeX、旧稿，整理文献矩阵 |
| 联网自搜 | 无本地材料时主动检索公开论文页、预印本、数据库摘要和 DOI |
| 文献检索 | 设计关键词，补充检索，记录纳入/排除理由和待核验项 |
| 框架构建 | 提炼研究问题、分类维度、方法谱系、争议和未来方向 |
| 任意主题综述 | 用户只给主题时，自动生成 RQ、检索来源、图表计划和综述 |
| 参考综述复现 | 按参考综述的数据来源、RQ 和图表类型合成新综述；需要评测时再对比效果 |
| 图表合成 | 根据本次文献统计数据按需生成趋势图、关系图、饼状图、流程图或思维导图 |
| 综述成稿 | 按“观点 -> 证据 -> 综合判断”写作，避免论文摘要堆叠 |
| 人工学术重写 | 修正证据链后降低模板化、清单化和 prompt 痕迹，输出更自然的学术正文 |
| 引用管理 | 保留引用证据链，不编造作者、年份、DOI、页码或结论 |
| 迭代修订 | 在已有综述上合并新文献、纠错、改结构、润色或重写 |

## 安装

把本目录放到 Agent Skills 可发现的位置，并确保 `SKILL.md` 位于目录根级。

示例：

```bash
mkdir -p .claude/skills
cp -a literature-review-skill .claude/skills/literature-review-skill
```

基础依赖用于 Office 转 Markdown、Markdown 转 Word：

```bash
pip install -r requirements.txt
```

其中 `PyMuPDF` 用于从 PDF 中抽取图片对象、页面图和疑似 Figure/Table 图题。

如需把 Mermaid 图渲染进 Word，在 `tools/` 下安装 Node 依赖：

```bash
cd tools
npm install
```

## 使用

在 Agent 中直接描述任务，例如：

- “帮我写一篇大模型幻觉检测的文献综述正文”
- “给我一个研究主题：RAG 幻觉抑制。请自动找文献、生成 RQ、合成图表并输出综述”
- “按 Two Decades of Artificial Intelligence in Education 这篇综述的数据来源和 RQ，一比一合成一篇新的 AIEd 综述并对比效果”
- “按照计划书，只做图表合成，不做参考图表内容分析”
- “我没有现成论文，请自己联网检索 RAG 幻觉抑制相关论文并写综述正文”
- “扫描这个文件夹里的论文，整理研究现状和未来方向，并生成综述正文”
- “基于已有综述补充 2024-2026 年的新文献”
- “把 related work 改成更像顶会论文的写法，保留引用”
- “这篇看起来太像 AI，请先修正证据链，再改成自然的学术综述写法”

建议同时提供：

- 研究主题或暂定题目
- 目标用途：课程论文、毕业论文、投稿论文、开题报告、基金申请等
- 篇幅、语言、引用格式
- 本地资料路径或已有稿件路径

说明：计划书中的图表类型是 skill 库需要支持的能力，不代表每篇综述都必须全部生成。只有用户要求、RQ 需要且数据足够时才生成对应图表。

## 项目结构

```text
literature-review-skill/
├── SKILL.md
├── prompts/
│   ├── intake.md
│   ├── project_scan.md
│   ├── research_question_analyzer.md
│   ├── literature_search.md
│   ├── reference_review_synthesis.md
│   ├── figure_table_handling.md
│   ├── outline_preview.md
│   ├── review_builder.md
│   ├── human_academic_rewrite.md
│   ├── review_self_check.md
│   ├── iteration_context.md
│   ├── merger.md
│   ├── correction_handler.md
│   └── style_reference.md
├── tools/
│   ├── docx_to_md.py
│   ├── pdf_extract_figures.py
│   ├── pptx_to_md.py
│   ├── md_to_docx.py
│   └── mermaid_render.py
└── requirements.txt
```

## 交付约定

默认输出到：

`outputs/{主题标识}/{主题标识}_{YYYYMMDDHHmmss}.md`

需要 Word 时生成同名 `.docx`。如果用户明确说“不要 md / 只要 Word”，Markdown 只作为内部中间稿，最终交付 `.docx`。除非用户明确要求覆盖，否则每轮修订都另存新版本。
