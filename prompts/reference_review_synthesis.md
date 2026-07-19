# 参考综述复现式生成

目标：支持两种工作方式：

1. 任意主题自动综述：用户只给研究主题时，自动生成适合该主题的 RQ、检索来源、筛选标准、图表类型和综述报告。
2. 参考综述复现式生成：用户给出参考综述或计划书时，按照参考综述的数据来源、研究问题和图表类型，合成一篇新的研究综述；若用户要求复现实验、效果评估或对比，再与参考综述进行效果对比。

本流程不做论文图表内容分析；不要求分析参考论文原图的视觉细节、颜色、布局或节点位置。只识别综述需要哪些数据、回答哪些 RQ、使用哪些图表类型，然后用本次检索/筛选得到的数据生成对应综述。

重要澄清：“与多组文献综述文章进行对比，生成效果良好”是论文实验/系统评测层面的验证要求，不是每篇自动生成综述正文的必备章节。

## 模式选择

- 如果用户只给研究主题，例如“生成 RAG 幻觉抑制综述”“生成智能教育综述”，进入任意主题自动综述模式。
- 如果用户明确给出参考综述、计划书、指定论文，或说“一比一合成/按这篇文章/按计划书”，进入参考综述复现模式。

## 任意主题自动综述模式

当用户只给一个研究主题时，Agent 应主动完成：

1. 根据主题生成 3-5 个研究问题 RQ。
2. 根据领域选择检索来源，例如：
   - 计算机/NLP/AI：Semantic Scholar、Google Scholar、arXiv、ACL Anthology、OpenReview、DBLP、IEEE、ACM。
   - 医学/生命科学：PubMed、PubMed Central、Crossref、Semantic Scholar。
   - 教育/社会科学：ERIC、Google Scholar、Semantic Scholar、Scopus/WoS 题录线索、期刊官网。
   - 综合主题：Google Scholar、Semantic Scholar、Crossref、OpenAlex、领域数据库。
3. 自动生成中英文关键词和布尔检索式。
4. 检索并筛选候选文献。
5. 生成文献矩阵。
6. 根据 RQ 按需生成对应图表，例如趋势图、主题分布图、方法分类图、关系图、对比表；无必要或数据不足时不强制生成。
7. 按 RQ 组织综述正文。
8. 输出检索限制和待核验项。

不要硬套 AIEd 的 RQ1-RQ5；AIEd RQ 只在参考综述复现模式下使用。

## 默认参考范式：AIEd 参考综述

若用户提到“按计划书”“按那篇 AIEd 综述”“Two Decades of Artificial Intelligence in Education”，采用以下参考范式：

- 参考综述：Two Decades of Artificial Intelligence in Education: Contributors, Collaborations, Research Topics, Challenges, and Future Directions
- 领域：Artificial Intelligence in Education (AIEd)
- 时间范围：2000-2019
- 文献类型：英文研究文章与会议论文
- 数据来源：Web of Science (WoS)、Scopus、ERIC、ICAIED、IJAIED

## 参考综述研究问题

- RQ1: What were the number of AIEd articles published from 2000 to 2019?
- RQ2: What were the top publication sources, countries/regions, and institutions?
- RQ3: What was the nature of collaboration among countries and institutions?
- RQ4: What were the most investigated research topics?
- RQ5: How did the intensity of research interest in these topics change?

## 检索来源复现

优先按参考综述来源检索：

1. Web of Science (WoS)
2. Scopus
3. Education Resources Information Center (ERIC)
4. International Conference on Artificial Intelligence in Education (ICAIED)
5. International Journal of Artificial Intelligence in Education (IJAIED)

如果当前环境无法访问 WoS、Scopus 或 ERIC，必须明确写出限制，并使用可访问来源近似复现，例如公开题录、Google Scholar、Semantic Scholar、Crossref、OpenAlex、DBLP、ERIC 公开页面、期刊/会议官网。不要声称已经访问了不可访问数据库。

## 检索词复现

AI 相关检索词：

- artificial intelligence
- machine intelligence
- intelligent support
- intelligent virtual reality
- chat bot*
- machine learning
- automated tutor*
- personal tutor*
- intelligent agent*
- expert system*
- neural network*
- natural language processing
- chatbot*
- intelligent system*
- intelligent tutor*

教育相关检索词：

- education
- college*
- undergrad*
- graduate
- postgrad*
- K-12
- kindergarten*
- corporate training*
- professional training*
- primary school*
- middle school*
- high school*
- elementary school*
- teaching
- learning

## 合成流程

1. 按参考综述来源和检索词收集候选文献。
2. 对候选文献去重。
3. 按主题相关性筛选文献。
4. 建立文献元数据表：题名、作者、年份、来源、国家/地区、机构、关键词、摘要、URL/DOI。
5. 对 topic code、缩写和展示名称进行英文规范化，按 RQ1-RQ5 统计或归纳数据；最近五年截止于最新完整年份。
6. 生成流程图、年度发文量柱状图和双五年 topic 词云；只有真实国家、机构或共著字段充分时才用 `tools/render_collaboration_networks.py` 生成合作连接图。参考 Figure 7/8 时优先生成国家/地区与机构两张力导向网络，保持“节点面积=子集发文量、线宽=合作强度、颜色=社区”的语义，并执行最小节点直径与最小标签字号门禁；不得用异构 bibliographic evidence map 替代。词云使用大画布、浅色简洁双面板并完整披露两个窗口的记录数与计数口径。流程图必须用实际字体度量验证每行文本在框内且不侵入图标保留区。每张图必须来自本次数据、全部使用英文标签并通过 report。若 topic-year 数据充分，再生成年度主题比例图回答 RQ5。
7. 建立 `evidence_ledger.json`，确保 RQ1-RQ5 的结论均有引用 key 和证据依据。
8. 按参考综述的问题结构合成完整 LaTeX 工程，并运行 `latex_delivery.md` 的质量门禁。
9. 仅当用户要求复现实验、效果评估或对比时，输出“合成效果对比”，说明自动合成稿与参考综述在 RQ 覆盖、图表类型、主题分析、引用标注上的对应关系。

## 输出要求

最终综述至少包含：

- 数据来源与检索策略
- 文献筛选说明
- RQ1-RQ5 的逐项回答
- 对应图表
- 主题分析
- 文献引用标注
- 可解析的 `references.bib` 与证据台账
- 通过验证的 LaTeX 源稿、图表和质量 reports
- 全英文标题、正文、表格和图表文字

可选内容：

- 与参考综述的效果对比：仅在用户明确要求复现实验、评测或对比时加入。

如果某些数据无法获得，例如机构、国家、合作关系，必须标注“数据不足/待核验”，不能编造。
