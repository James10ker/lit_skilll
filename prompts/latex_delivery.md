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
│   └── evidence_ledger.json
└── reports/
    ├── figure_*.report.json
    └── latex_quality.report.json
```

参考复现任务默认至少包含四张基于本次文献集合生成的图：流程图、年度发文量柱状图、连接图、双五年 topic 词云图。若 RQ 要求 topic-year 演化、来源分布或其他统计，再增加对应图表。普通综述只生成与 RQ 有关且数据充分的图。

## LaTeX 契约

- 输出完整 `.tex` 文档，不输出围栏代码片段。
- 中文稿使用 `ctexart` 或用户给定模板；英文稿使用 `article` 或目标期刊模板。
- 至少包含题名、摘要、关键词、引言、数据来源与方法、结果、讨论、结论和参考文献。
- 图像使用相对路径 `\includegraphics{figures/...}`；每个 figure/table 同时有 `\caption` 与 `\label`，正文使用 `\ref` 引用。
- 文献引用使用 `\cite{key}` 与 `references.bib`，不得只写作者年份纯文本冒充可解析引用。
- 正文不保留 Markdown 标题、代码围栏、执行说明、prompt、自检清单、TODO、待插入或“该图用于回答 RQx”等过程痕迹。
- 图题说明数据来自本次筛选集合；访问限制、人工编码和模型辅助主题标注在方法或限制中如实披露。

## 证据台账

写作前生成 `data/evidence_ledger.json`。每个关键结论记录：

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

## 硬门禁

完成初稿后运行：

```bash
python3 tools/validate_latex_review.py \
  --input outputs/{topic}/review.tex \
  --report outputs/{topic}/reports/latex_quality.report.json \
  --min-words 3000 \
  --min-figures 4
```

`--min-figures 4` 适用于参考综述复现任务；普通综述按已批准的图表计划调整。若环境有 `latexmk`，再运行：

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error outputs/{topic}/review.tex
```

只有以下条件全部满足才可交付：

1. 每个图表 report 的 `validation.passed = true`。
2. `latex_quality.report.json` 的 `passed = true`。
3. 所有 RQ 在 discussion/结果中有直接回答，并可回溯到证据台账。
4. 图表统计总数、正文数字、纳入文献数和参考文献 key 一致。
5. 有 LaTeX 编译器时编译成功；没有时明确报告未执行编译，但不得跳过静态门禁。

任何门禁失败都要继续修订并重跑，不得把未达标初稿交付给用户。
