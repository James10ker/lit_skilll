# Collaboration Network Module

本模块用于按参考综述 *Two Decades of Artificial Intelligence in Education* 的 Figure 7/8 形式生成真实合作网络。它不复制参考图，而是从本次论文记录中的作者、机构或国家字段重新统计合作边。

## 正确工具

```text
tools/render_collaboration_networks.py
```

旧工具 `tools/render_bibliometric_network.py` 生成 author/topic/journal/year/affiliation 异构证据图，只能明确称为 **bibliographic evidence map**。它不是 scientific collaboration network，不得用于复现 Figure 7/8。

## 数据语义

支持 JSON/CSV；JSON 可以是记录数组或 `{ "records": [...] }`。常用字段：

```json
{
  "title": "Paper title",
  "authors": ["Author A", "Author B"],
  "institutions": ["Institution A", "Institution B"],
  "countries": ["US", "CA"]
}
```

兼容字段：

- 作者：`authors` / `author` / OpenAlex `authorships[].author.display_name`
- 机构：`institutions` / `affiliations` / `author_units` / OpenAlex `authorships[].institutions[].display_name`
- 国家：`countries` / `country` / `country_codes` / OpenAlex authorship country fields

边只来自同一篇论文中同维度实体的真实共现：

- `authors`：作者共著边
- `institutions`：跨机构共同署名边
- `countries`：跨国家/地区共同署名边

禁止生成 author--topic、author--journal、topic--year 等混合边并称为合作网络。

## 参考论文式视觉编码

- 节点面积：当前字段覆盖子集中的发文量
- 边宽：共同署名论文次数
- 节点颜色：基于加权网络检测的合作社区
- 布局：确定性 force-directed node-link layout
- 筛选：按发文量、加权度、度数选择 top-N；诱导子图中的孤立候选可以省略，但不得新增边

每张图同时输出 SVG 与 PNG。图内徽标和正文图注必须披露字段覆盖范围；例如只有扩充论文有 affiliation 时，应写明 `49 / 199 included records`，不能暗示全语料分析。

## 命令

同时生成参考论文对应的国家/地区和机构网络：

```bash
python3 tools/render_collaboration_networks.py \
  --input included_records.json \
  --output-dir outputs/figures \
  --dimensions countries,institutions \
  --top-n 30 \
  --max-labels 20 \
  --min-coverage 0.20 \
  --min-multi-party-records 3 \
  --report outputs/reports/collaboration_networks.report.json
```

作者共著网络：

```bash
python3 tools/render_collaboration_networks.py \
  --input included_records.json \
  --output-dir outputs/figures \
  --dimensions authors \
  --report outputs/reports/author_collaboration.report.json
```

默认输出：

```text
country_collaboration_network.svg/png
institution_collaboration_network.svg/png
author_collaboration_network.svg/png
```

## 数据门禁

默认要求每个请求维度：

- 字段覆盖率至少 20%；
- 至少 3 篇论文具有两个或以上同维度实体；
- 至少存在一条真实合作边；
- top-N 诱导图仍包含合作边；
- 节点、标签无重叠，标签不越界。

不足时不生成替代图，report 的 `skipped` 会记录原因并令 `validation.passed=false`。可以根据研究设计调整覆盖率阈值，但必须在方法、图注和局限性中披露。

## Report 契约

关键字段：

```text
input_records
requested_dimensions
semantic_contract
networks.{dimension}.input_stats
networks.{dimension}.selection
networks.{dimension}.layout_checks
skipped
validation
```

最小通过条件：

```python
assert report["validation"]["true_collaboration_edges_only"]
assert report["validation"]["no_inferred_entities_or_edges"]
assert report["validation"]["all_requested_dimensions_rendered"]
assert report["validation"]["all_layout_checks_passed"]
assert report["validation"]["passed"]
```

## 正文写法

图注至少说明：字段覆盖记录数、原始或可见节点数、边数、top-N 规则、节点面积/线宽/颜色语义，以及结果不代表全领域的限制。若所有 affiliation 数据都来自扩充子集，应在 RQ 结果和 Limitations 中重复该边界。
