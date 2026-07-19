---
name: literature-review-skill
description: "从用户爬取的论文/PDF/元数据独立生成全英文高质量文献综述或复现参考综述：完成证据提取、RQ 综合、流程图、年度发文量图、连接图、双五年 topic 词云、引用与主动质量门禁，达标后直接交付完整 LaTeX 工程。适用于 Claude Code + DeepSeek 或其他模型执行综述写作、AIEd 参考论文复现和图表合成。| Evidence-grounded, English-only literature review generation with validated figures, self-correction, and compile-ready LaTeX delivery."
allowed-tools: Read, Write, Edit, Grep, Glob, WebSearch, Bash
---

# 论文综述撰写 Skill

本技能覆盖 **选题澄清** -> **资料扫描或联网自搜** -> **文献检索与筛选** -> **证据台账** -> **研究问题生成/对齐** -> **可验证图表合成** -> **研究问题回答** -> **LaTeX 成稿** -> **主动质检与修订** 的完整流程。参考复现或系统评测任务可加入 **效果对比**。分步指令位于 `prompts/`；执行每一步前先读取对应文件。

支持两种模式：

- **任意主题自动综述模式**：用户只给一个研究主题时，自动生成合适的 RQ、检索来源、筛选标准、图表类型和综述正文。
- **参考综述复现模式**：用户给出参考综述或计划书时，按参考综述的数据来源、RQ 和图表类型合成对应综述；只有用户要求复现评测、效果比较或论文实验输出时，才加入效果对比。

默认交付物是通过门禁的 **完整 LaTeX 综述工程**，不是研究计划、开题报告、写作方案或 Markdown 草稿。只有用户明确要求“研究计划、开题、proposal、写作计划、只要提纲/检索策略”时，才停留在计划/提纲层面。

## 触发条件

在用户提到以下任务时启用：

- 论文综述、文献综述、研究现状、国内外研究现状、相关工作、survey、review、systematic review、scoping review、narrative review
- 用户随便给一个研究主题，希望自动找文献、自动设定 RQ、自动生成综述
- 没有现成论文材料，希望 Agent 自己联网找论文、筛选文献并写综述
- 按某篇参考综述的数据来源、研究问题和图表类型，一比一合成新的综述；在复现实验或评测任务中对比效果
- 提到“计划书”“AIEd 综述”“Two Decades of Artificial Intelligence in Education”“图表合成”“只做图表合成”
- 对一批论文/PDF/Word/PPT/笔记进行归纳、比较、分类、写成综述
- 根据文献统计数据生成趋势图、关系图、饼状图、流程图或思维导图
- 补充、重写或润色已有综述章节，并要求保留引用、逻辑和证据链

## 产出原则

- 最终论文默认且强制使用英语。标题、摘要、关键词、章节标题、正文、表头、图题、图注、坐标轴、图例和图中节点标签必须全部为英语；仅原始参考文献条目中的不可译专名可保留原文。
- 不编造文献、作者、年份、DOI、页码或实验结论；无法确认的内容标记为“待核验”。
- 区分事实、论文观点与作者综合判断；避免把单篇论文结论泛化成领域共识。
- 所有关键判断应能回溯到具体文献或用户提供材料。
- 正文声明的 RQ、`evidence_ledger.json` 覆盖的 RQ 和图表计划必须使用同一组编号；不得出现正文只有 RQ1--RQ3 而报告声称覆盖 RQ1--RQ5 的情况。
- 必须报告可用全文、仅摘要和仅元数据记录的数量及比例。若多数记录没有全文，方法、实验效果和细节性结论只能基于有全文的子集；不得把标题/摘要级综合写成全量全文综述。
- 默认不做论文图表内容分析，不分析参考图表的颜色、布局、节点位置或视觉细节。
- 图表默认是“图表合成”：根据本次检索/筛选得到的文献数据，生成与参考综述同类型、同功能的新图表。
- 参考复现任务默认生成流程图、年度发文量柱状图和双五年 topic 词云；合作数据充分时再生成连接图。普通综述按 RQ 与数据生成必要图表。所有已生成图必须通过各自 report 的几何与数据校验。参考 Figure 7/8 式连接图必须使用力导向 node-link 形式：节点面积表示子集发文量、线宽表示重复合作强度、颜色表示网络社区。
- 双五年 topic 词云以用户指定截止年划分“最近五年”和“此前五年”，两个窗口相邻且不重叠；topic 缺失时先完成透明的人工/模型辅助编码台账，不得编造作者关键词。默认使用大画布、白色或浅色背景、简洁且层级清晰的双面板布局，优先完整容纳规范化 topic 标签；字体大小只表示各自窗口内的频次，图注必须披露窗口样本量与计数口径。
- 主题统计前必须把代码、缩写和自然语言标签映射到唯一规范标签；同一主题不得以 `APPLICATION` 和 `AI Applications in Education` 等多个名称重复计数。
- “最近五年”只能截止到最新完整年份。当前年或明确不完整年份可出现在年度趋势图中，但不得进入完整五年窗口，也不得支撑跨窗口百分比结论。
- 合作网络只能使用真实的国家、机构或作者共著字段。所需字段缺失或覆盖不足时跳过该图并披露限制，不得用 author/topic/journal/year 混合共现网络冒充合作网络。
- “与多组文献综述文章进行对比，生成效果良好”属于论文实验/系统评测层面的验证要求，不代表每篇自动生成的综述正文都必须写对比章节。
- 任意主题模式下，不要强行套用 AIEd 的 RQ；应根据用户主题自动生成对应 RQ 和图表计划。
- 若参考综述来源不可访问，例如 WoS、Scopus、ERIC 无权限，必须标明限制，并使用可访问来源近似复现；不得声称获得了无法访问的数据。
- 最终正文必须经过“人工学术风格重写”：先修正事实、数量、图表来源和引用证据链，再降低模板化、清单化和 prompt 痕迹。该步骤用于提升学术可读性和可信度，不用于掩盖 AI 使用或包装不可核验内容。
- 最终默认交付 `review.tex`、`references.bib`、图表 PNG/SVG、图表 reports、纳入记录和 `evidence_ledger.json`；只有全部质量门禁通过才输出。

## 工具与资料处理

| 任务 | 建议方式 |
|------|----------|
| 加载分步指令 | `Read` -> `prompts/*.md`，按下方映射执行 |
| 扫描本地论文与资料 | 先列目录，再按题名、摘要、引言、方法、实验、结论、参考文献精读 |
| 无本地材料时联网找论文 | 读 `prompts/literature_search.md`；用 WebSearch 检索论文页、预印本、数据库摘要页、综述和基准论文；记录 URL/DOI/可访问性 |
| 任意主题自动综述 | 读 `prompts/reference_review_synthesis.md`；未给参考综述时，自动生成主题对应 RQ、检索来源、图表计划和综述结构 |
| 参考综述复现 | 读 `prompts/reference_review_synthesis.md`；给出参考综述时，按参考综述的数据来源、RQ 和图表类型合成报告；仅在复现实验/评测要求下加入效果对比 |
| Office 输入转换 | Word/PPT 作为输入时使用仓库已有转换工具；这不改变最终 LaTeX 交付格式 |
| 图表合成 | 先读 `prompts/figure_table_handling.md`；所有图必须由本次记录生成并输出验证 report |
| 年度图与双五年词云 | `python3 tools/render_temporal_topic_figures.py --input {records.json} --output-dir {figures_dir} --prefix {topic} --start-year {start} --end-year {end} --report {report.json}` |
| 合作连接图 | `python3 tools/render_collaboration_networks.py --input {records.json} --output-dir {figures_dir} --dimensions countries,institutions --report {report.json}`；作者共著改用 `--dimensions authors` |
| 流程图 | `python3 tools/render_review_figure1.py --spec {spec.json} --output {figure.svg} --report {report.json}` |
| LaTeX 静态门禁 | `python3 tools/validate_latex_review.py --input {review.tex} --report {quality.json} --language english --evidence-ledger {ledger.json} --required-rqs {RQ1,...} --figure-report {figure.report.json} --min-words 3000 --min-figures {approved_count}` |
| 人工学术风格重写 | 读 `prompts/human_academic_rewrite.md`；去除模板化结构和机械表达，保留证据链，不新增未核验内容 |
| 外部检索 | 优先使用权威数据库或搜索入口；可结合 WebSearch 查询 Google Scholar、Semantic Scholar、PubMed、IEEE Xplore、ACM DL、arXiv、CNKI 等公开信息 |

## Prompt 文件映射

| 步骤 | 文件 | 用途 |
|------|------|------|
| Step 1 | `prompts/intake.md` | 明确主题、范围、综述类型、篇幅、引用格式和交付形式 |
| Step 2 | `prompts/project_scan.md` | 扫描用户提供的论文、笔记、课程材料、代码/实验资料 |
| Step 3 | `prompts/research_question_analyzer.md` | 提炼研究问题、分析维度、分类框架和综述主线 |
| Step 4 | `prompts/literature_search.md` | 检索、筛选、去重、记录文献信息和证据强度 |
| Step 5 | `prompts/reference_review_synthesis.md` | 任意主题自动综述或按参考综述的数据来源、RQ 和图表类型进行复现式合成 |
| Step 6 | `prompts/figure_table_handling.md` | 根据本次文献统计数据生成同类型图表，不做图表内容分析 |
| Step 7 | `prompts/outline_preview.md` | 成稿前给出提纲、文献矩阵、图表计划和论证路线预览 |
| Step 8 | `prompts/review_builder.md` + `prompts/style_reference.md` | 撰写综述正文、引用、图表和结论 |
| Step 9 | `prompts/review_self_check.md` | 内部自检：覆盖度、引用、逻辑、重复、学术表达、图表必要性 |
| Step 10 | `prompts/human_academic_rewrite.md` | 在证据链修正后进行人工学术风格重写，降低 AI 模板感 |
| Step 11 | `prompts/latex_delivery.md` | 生成完整 LaTeX 工程并执行结构、引用、图表和残留指令硬门禁 |
| 迭代 | `prompts/iteration_context.md` | 判断是在已有综述上增补、删改、重构还是纠错 |
| 迭代 | `prompts/merger.md` | 合并新增文献、材料或用户意见 |
| 迭代 | `prompts/correction_handler.md` | 纠正文献事实、引用、观点归属、结构或风格问题 |

## 主流程

1. `Read prompts/intake.md`，确认任务边界；信息不足时只问最关键的问题。
2. `Read prompts/project_scan.md`，扫描用户提供材料；Office 文件先转换为 Markdown。若用户没有提供材料或目录为空，不要停止，转入 `literature_search.md` 的联网自搜模式。
3. `Read prompts/research_question_analyzer.md`，形成研究问题、分析维度和初步分类。
4. `Read prompts/literature_search.md`，补充检索并筛选文献；记录纳入/排除理由，并建立逐条关键结论到引用 key 的 `evidence_ledger.json`。
5. `Read prompts/reference_review_synthesis.md`。若用户只给主题，自动生成主题对应 RQ、检索来源和图表计划；若用户要求按参考综述或计划书合成，则对齐参考综述的数据来源、RQ 和图表类型。不要把系统评测中的“多综述对比”误写成每篇正文必备章节。
6. `Read prompts/figure_table_handling.md`，根据本次文献统计数据合成图表。参考复现任务默认生成流程图、年度柱状图和双五年 topic 词云；合作字段充分时才用 `render_collaboration_networks.py` 生成真实作者/国家/机构合作图。不得调用异构 author/topic/journal/year 图冒充参考 Figure 7/8。每张已生成图的 report 必须通过；普通综述按 RQ 生成。
7. `Read prompts/outline_preview.md`，仅在需要用户确认范围或用户明确要求“先给提纲/检索策略”时输出预览；不要把预览命名为研究计划。
8. `Read prompts/review_builder.md` 与 `prompts/style_reference.md`，撰写正文并按要求落盘；当用户说“写综述/生成综述/撰写研究现状/related work”时，必须进入本步，而不是只交付计划。
9. `Read prompts/review_self_check.md`，内部自检后修订；不要把自检清单写进正文。
10. `Read prompts/human_academic_rewrite.md`，对最终正文做人工学术风格重写；不得新增未核验事实，不得把估算、人工编码或二级综述汇总包装成精确统计。
11. `Read prompts/latex_delivery.md`，生成完整 LaTeX 工程，运行全部图表 report 校验和 `validate_latex_review.py`。失败时自动修订并重跑；只有全部通过才交付。

## 迭代模式

当用户在已有综述基础上要求“补几篇文献、改结构、润色、降重、修正引用、补国内外现状、重写相关工作”等，默认进入迭代模式：

- 新增材料或扩展章节：读 `iteration_context.md` -> `merger.md`
- 指出错误、引用不准、观点归属不清：读 `iteration_context.md` -> `correction_handler.md`
- 交付文件时保留旧版本；新版本使用独立输出目录或时间戳子目录，主文件始终为 `review.tex`

## Agent 自检清单

```
□ 已读取本轮对应 prompt
□ 用户要求写综述时，交付的是综述正文/综述草稿，而不是研究计划或开题方案
□ 未编造不存在的文献、作者、年份、DOI、页码或结论
□ 每个关键论断可追溯到文献或用户材料
□ 无本地材料时，已主动联网检索并保留来源 URL/DOI/访问日期；不可核验条目标为待核验
□ 用户只给研究主题时，已自动生成适合该主题的 RQ、检索来源、筛选标准和图表计划，未硬套 AIEd 模板
□ 若按参考综述复现，已对齐参考综述的数据来源、RQ 和图表类型；只有复现实验/评测任务才加入效果对比
□ 图表是基于本次文献统计数据按需合成的同类型图表；未默认分析或复制参考论文原图，也未为凑数量编造图表
□ 参考复现任务已生成流程图、年度柱状图和双五年 topic 词云；合作字段充分时已生成连接图，且每个已有 report 均 `validation.passed=true`
□ 双五年窗口相邻且不重叠；topic 来源和逐篇编码可追溯
□ 最近五年截止于最新完整年份；不完整年份未进入窗口比较
□ topic 代码、缩写和展示标签已归一化，同一概念未重复计数
□ 合作网络有真实合作字段支撑，采用论文式 node-link 语义（节点面积=子集发文量、线宽=合作强度、颜色=社区）；数据不足时已跳过而非生成替代性混合网络
□ 连接图最小节点直径与最小标签字号门禁已通过，并在论文实际栏宽下可读；流程图逐框实测文字未越界，统一设计系统已应用且没有装饰图标占位
□ 若 WoS、Scopus、ERIC 等来源不可访问，已明确标注访问限制和近似复现来源
□ 综述不是论文摘要堆叠，而是按问题、方法、证据和争议综合
□ 已说明检索范围、筛选标准和残余不确定性
□ 已进行人工学术风格重写：删除机械图注、模板化 RQ 填空、过度粗体/列表和空泛宏大判断
□ 重写没有新增未核验文献、数据或结论，也没有掩盖 AI 生成、估算数据或人工编码事实
□ 引用格式与用户要求一致；不确定引用已标记待核验
□ 关键结论已写入 `evidence_ledger.json`，引用 key 可解析，正文数字与图表/纳入记录一致
□ 最终交付为完整 `.tex` + `.bib` + figures/data/reports 工程，不以 Markdown 草稿代替
□ 标题、正文、表格及所有图形文字均为英语，且使用 `--language english` 验证
□ `validate_latex_review.py` 已通过；有 LaTeX 编译器时已编译通过
```
