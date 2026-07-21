# Step 4: 文献检索与筛选

目标：获取候选文献元数据并完成初筛；不要在本步骤直接凭搜索结果撰写综述。检索完成后必须进入 `structured_literature_pipeline.md`。

## 检索策略

- 组合关键词：中文、英文、同义词、上位词、具体方法名、应用场景。
- 优先权威来源：Google Scholar、Semantic Scholar、PubMed、IEEE Xplore、ACM DL、Springer、ScienceDirect、arXiv、CNKI、万方等。
- 使用滚雪球法：从高质量综述、经典论文和最新论文的参考文献/被引文献扩展。
- 默认从 OpenAlex、Crossref、Semantic Scholar、arXiv、PubMed 等可访问接口取得约 200–500 条候选元数据；首版工具至少联合 OpenAlex 与 Crossref。
- 此阶段只收集题名、作者、年份、来源、摘要、关键词、DOI、arXiv ID、引用量、开放获取状态和 URL，不把索引记录当作全文证据。

## 参考综述复现检索

当用户要求“按参考综述”“按计划书”“一比一合成”“AIEd 综述复现”时，不采用泛泛的最新论文检索策略，而是优先复现参考综述的数据来源和检索范围。

默认参考综述为 *Two Decades of Artificial Intelligence in Education: Contributors, Collaborations, Research Topics, Challenges, and Future Directions*。其来源与范围为：

- Web of Science (WoS)
- Scopus
- Education Resources Information Center (ERIC)
- International Conference on Artificial Intelligence in Education (ICAIED)
- International Journal of Artificial Intelligence in Education (IJAIED)
- 时间范围：2000-2019
- 文献类型：英文研究文章与会议论文

执行要求：

1. 先尝试按 WoS、Scopus、ERIC、ICAIED、IJAIED 的来源逻辑查找文章。
2. 若当前环境无法访问 WoS、Scopus 或 ERIC，必须记录“无法访问/无权限”，并用公开可访问来源近似复现。
3. 不得声称已经完整检索 WoS、Scopus 或 ERIC，除非确实访问并获得结果。
4. 保留每个来源的检索记录，便于最后和参考综述对比。
5. 只做文章爬取、筛选和元数据统计；不做参考论文图表内容分析。

## 无本地材料：联网自搜模式

当用户没有提供论文 PDF、BibTeX 或文献目录时，Agent 应主动联网检索，不要停下来要求用户先准备材料。

若用户只给研究主题，应先根据主题判断学科，再选择合适来源和关键词；不要默认套用 AIEd 的 WoS/Scopus/ERIC/ICAIED/IJAIED 方案。

优先检索和交叉核验：

- 论文检索与索引页：Semantic Scholar、Google Scholar 搜索结果、OpenAlex、Crossref、DBLP、PubMed。
- 开放全文：arXiv、ACL Anthology、PubMed Central、OpenReview、HAL、机构主页、会议官方论文页。
- 出版商摘要页：IEEE Xplore、ACM DL、Springer、ScienceDirect、Wiley、Nature、Science 等；若无法读取全文，只使用可见摘要/元数据并标注限制。
- 中文资料：CNKI、万方、维普、学位论文库；若不可访问，只记录题录线索并标注待核验。

检索顺序：

1. 用 3-6 组中英文关键词找最新综述、系统综述或 survey，作为入口文献。
2. 找经典奠基论文和高被引代表作。
3. 找近 2-3 年顶会/顶刊/高质量预印本，补齐前沿进展。
4. 对每篇候选文献至少交叉核验题名、作者、年份、来源和 URL/DOI。
5. 只把可核验的文献写入正式引用；无法确认的放入“待核验候选文献”。

不要绕过付费墙、验证码、登录限制或批量下载限制。能看到摘要就只基于摘要和可公开元数据判断，不把未读全文的细节写成确定结论。

## 筛选标准

写明纳入与排除规则，例如：

- 时间范围
- 研究对象或任务范围
- 文献类型：期刊、会议、预印本、学位论文、标准/白皮书
- 质量要求：同行评审、引用量、数据充分性、方法透明度

## 输出格式

维护“检索记录”：

- 查询词/数据库/日期
- 命中数量或代表性结果
- 纳入文献及理由
- 排除文献及理由
- 待核验项

同时维护“候选文献表”：

| 文献 | 年份 | 来源 | URL/DOI | 可访问性 | 纳入状态 | 用途 |
|------|------|------|---------|----------|----------|------|

可访问性统一填写：`metadata_only`、`abstract_only`、`section_level`、`fulltext`。旧值“全文可读、仅摘要、题录可见、待核验”只作为输入兼容，不得继续写入新 Paper Store。

候选表不是最终证据库。检索后读取 `prompts/structured_literature_pipeline.md`，生成统一 Paper Store、版本关系、Paper Card、Theme Synthesis 和 Claim–Evidence Store v2。

若无法联网或数据库不可访问，明确说明限制，并基于用户材料继续写作。
