# Step 5A: 结构化文献处理流水线

目标：在检索与写作之间建立可验证的数据层，使引用深度不超过实际读取深度。

执行前读取 `references/literature_pipeline.md`。本步骤使用同一流水线中的工具模块，不默认拆分为多个 Agent。

## 必须产出

- `data/candidates.json`：约 200–500 条 API 元数据候选及各来源失败记录。
- `data/paper_store.json`：去重和版本合并后的统一 Paper 记录。
- `data/screening.json`：规则过滤、语义筛选决定和逐条理由；通常纳入 80–120 篇。
- `data/fulltext_documents/`：仅保存合法获得并成功解析的结构化正文。
- `data/paper_cards.json`：每篇纳入论文的结构化 Paper Card。
- `data/theme_syntheses.json`：每组 15–25 篇的主题/方法/时期综合。
- `data/evidence_ledger.json`：Claim–Evidence Store v2。
- `reports/evidence_validation.report.json`：证据权限硬门禁报告。

## 执行顺序

1. 根据主题与 RQ 生成检索式，从至少两个可用 API 获取元数据。默认：

   ```bash
   python3 tools/run_literature_pipeline.py search \
     --query "{query}" --sources openalex,crossref --limit 300 \
     --output outputs/{topic}/data/candidates.json
   ```

   API 失败必须写入 `source_failures`。不得静默缩小为单一来源。

2. 用 DOI、arXiv ID、规范化标题及作者—年份联合规则去重。把预印本、会议版和期刊版合并到同一 `work_id`；分别保留正式引用版本与实际读取版本。
3. 先做确定性规则过滤，再做模型语义筛选。筛选需同时考虑相关性、对象、方法透明度、来源质量、经典性、时效性和主题多样性；引用量不得成为唯一标准。防止结果过度集中于同一方法、团队或数据集。

   ```bash
   python3 tools/run_literature_pipeline.py screen \
     --input outputs/{topic}/data/candidates.json --query "{query}" --target 100 \
     --output outputs/{topic}/data/screening.json
   ```

   `included_rule_stage` 仍须模型确认研究对象、方法适配和主题覆盖；模型决定必须回写理由，不能把规则分数直接当最终纳入结论。
4. 先规划论点，再分配读取深度。方向存在性可停留于摘要；方法结构读取 Method；性能数字读取 Experiments/Results 与表格；局限性读取 Discussion/Limitations；核心论文读取关键章节或全文。20–50 篇核心论文只是预算起点，不是固定截断线。
5. 开放全文按 JATS/XML、HTML、LaTeX、可解析 PDF、OCR PDF 的优先级尝试。当前工具确定性支持 JATS/XML、HTML 和可解析 PDF；LaTeX/OCR 未实现时必须显式标记失败。不得绕过付费墙、登录、验证码或批量限制。

   ```bash
   python3 tools/run_literature_pipeline.py fetch-fulltext \
     --paper-store outputs/{topic}/data/paper_store.json --paper-id {paper_id} \
     --raw-dir outputs/{topic}/data/fulltext_raw \
     --output outputs/{topic}/data/fulltext_documents/{paper_id}.json
   ```
6. 获取失败时保持 `abstract_only` 或 `metadata_only`。不得根据摘要补写方法细节、实验数字、消融、局限或因果结论。
7. 建立 Paper Card；不可用字段放入 `unresolved_fields`，不得补全。
8. 每 15–25 篇按主题、方法或时期生成 Theme Synthesis。只综合 Card 和已定位证据，不重新自由推断原文。
9. 为每个拟写入正文的重要判断创建独立 claim。区分 `existence_verified` 与 `claim_supported`，并记录 relation、置信度、章节、页码/段落和表格定位。

   可用 `extract-evidence` 从已解析文档中按论点和章节召回候选块。工具输出始终是 `candidate_only` 且 `claim_supported=false`；必须核对原文后才能升级为证据。
10. 写作前运行：

    ```bash
    python3 tools/run_literature_pipeline.py validate-evidence \
      --ledger outputs/{topic}/data/evidence_ledger.json \
      --paper-store outputs/{topic}/data/paper_store.json \
      --report outputs/{topic}/reports/evidence_validation.report.json
    ```

    未通过时不得进入 `review_builder.md`。

11. 写作后把每个 verified claim 的最终句子和 citation keys 回写到 ledger，并运行 `verify-citations`；没有 `manuscript_text` 的论点只能得到未完成语义定位的警告。

## 降级规则

- 只有元数据：仅用于论文存在性、作者、年份、来源及发表量统计。
- 只有摘要：仅用于摘要明确表达的背景、研究方向、粗粒度方法和主要发现。
- 章节级：只能使用实际解析到并有定位的章节内容。
- 全文级：仍需具体证据定位；“全文可读”不等于所有生成论点自动成立。
- 证据不足：降低论点强度、改写为不确定判断、补充读取，或删除论点。
