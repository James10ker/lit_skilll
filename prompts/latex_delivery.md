# LaTeX 直接交付与质量门禁

目标：交付可编译、可追溯、图文一致的完整 LaTeX 综述工程。除非用户明确指定其他格式，不输出 Markdown 或 Word 作为主交付物。

## 工程结构

```text
outputs/{topic}/
├── review.tex
├── references.bib
├── figures/
│   ├── review_flow.png
│   ├── annual_publications.png
│   ├── bibliometric_network.png
│   └── topic_wordcloud.png
├── data/
│   ├── included_records.json
│   ├── paper_store.json
│   ├── paper_cards.json
│   ├── theme_syntheses.json
│   └── evidence_ledger.json
└── reports/
    ├── evidence_validation.report.json
    ├── figure_*.report.json
    └── latex_quality.report.json
```

参考复现任务默认包含三张基于本次文献集合生成的图：流程图、年度发文量柱状图和双五年 topic 词云图。只有真实合作字段充分时才加入连接图。若 RQ 要求 topic-year 演化、来源分布或其他统计，再增加对应图表。普通综述只生成与 RQ 有关且数据充分的图。

## LaTeX 契约

- 输出完整 `.tex` 文档，不输出围栏代码片段。
- 使用 `article` 或目标期刊英文模板；不得使用 `ctexart`，也不得加载仅为中文排版服务的字体包。
- 标题、摘要、关键词、章节标题、正文、表头、图题、图注及图内所有标签必须为英语。
- 至少包含题名、摘要、关键词、引言、数据来源与方法、结果、讨论、结论和参考文献。
- 图像使用相对路径 `\includegraphics{figures/...}`；每个 figure/table 同时有 `\caption` 与 `\label`，正文使用 `\ref` 引用。
- 文献引用使用 `\cite{key}` 与 `references.bib`，不得只写作者年份纯文本冒充可解析引用。
- 正文不保留 Markdown 标题、代码围栏、执行说明、prompt、自检清单、TODO、待插入或“该图用于回答 RQx”等过程痕迹。
- 图题说明数据来自本次筛选集合；访问限制、人工编码和模型辅助主题标注在方法或限制中如实披露。

## 证据台账

写作前生成 Claim–Evidence Store v2。完整字段、访问权限矩阵和示例见 `references/literature_pipeline.md`。旧版以下结构仅允许读取兼容，不再作为新任务输出：

```json
{
  "claim_id": "RQ4-C03",
  "claim": "需要写入正文的综合判断",
  "sources": ["bibkey1", "bibkey2"],
  "evidence": ["摘要、结果或全文中的可核验依据"],
  "confidence": "high|medium|low",
  "limitations": "适用范围与不确定性"
}
```

没有来源的判断不得进入最终正文；只有二级综述支持时，必须标明是二级证据。topic 若由模型从摘要或全文归纳，应保留文献到 topic 的编码记录，不得包装成作者原始关键词。

先单独运行证据权限门禁；失败时不得生成定稿。`existence_verified` 只证明论文真实存在，`claim_supported` 才表示定位到的内容支持该论点。

正文完成后运行引用审计：

```bash
python3 tools/run_literature_pipeline.py verify-citations \
  --input outputs/{topic}/review.tex \
  --ledger outputs/{topic}/data/evidence_ledger.json \
  --paper-store outputs/{topic}/data/paper_store.json \
  --report outputs/{topic}/reports/citation_verification.report.json
```

## 硬门禁

完成初稿后运行：

```bash
python3 tools/validate_latex_review.py \
  --input outputs/{topic}/review.tex \
  --report outputs/{topic}/reports/latex_quality.report.json \
  --language english \
  --evidence-ledger outputs/{topic}/data/evidence_ledger.json \
  --paper-store outputs/{topic}/data/paper_store.json \
  --required-rqs RQ1,RQ2,RQ3,RQ4,RQ5 \
  --figure-report outputs/{topic}/reports/figure_flow.report.json \
  --figure-report outputs/{topic}/reports/figure_temporal.report.json \
  --min-words 3000 \
  --min-figures 3
```

示例按三张默认图设置。若合作字段充分并生成了连接图，追加相应的 `--figure-report` 并将 `--min-figures` 调为 4；普通综述按已批准的图表计划调整。若环境有 `latexmk`，再运行：

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error outputs/{topic}/review.tex
```

只有以下条件全部满足才可交付：

1. 每个图表 report 的 `validation.passed = true`。
2. `latex_quality.report.json` 的 `passed = true`，其中 evidence ledger 覆盖全部 RQ，且所列图表 reports 全部通过。
3. 所有 RQ 在 discussion/结果中有直接回答，并可回溯到证据台账。
4. 图表统计总数、正文数字、纳入文献数和参考文献 key 一致。
5. 有 LaTeX 编译器时编译成功；没有时明确报告未执行编译，但不得跳过静态门禁。
6. `required_language` 为 `english` 且 `cjk_character_count` 为 0；图表源文件中的可见标签也已人工或程序检查为英语。

任何门禁失败都要继续修订并重跑，不得把未达标初稿交付给用户。
