# Bibliometric Network Module

本文说明新增的异构文献计量连接图模块，用于生成类似参考综述 Figure 7/8 的白底彩色网络图。模块不会抽取或复制参考论文原图，而是使用本次爬取或筛选得到的论文元数据重新合成同类型连接图。

## 1. 模块文件

```text
tools/render_bibliometric_network.py
```

示例输入：

```text
tools/examples/aied_bibliometric_network_records.json
```

示例输出：

```text
outputs/figures/aied_bibliometric_network.svg
outputs/figures/aied_bibliometric_network.png
outputs/figures/aied_bibliometric_network.report.json
```

## 2. 数据字段

模块支持 JSON 或 CSV。推荐 JSON 结构：

```json
{
  "records": [
    {
      "title": "Paper title",
      "authors": ["Author A", "Author B"],
      "journal": "Journal name",
      "year": 2024,
      "topics": ["Topic one", "Topic two"],
      "affiliations": ["Institution A", "Institution B"],
      "citations": 123
    }
  ]
}
```

CSV 字段同名即可。多值字段可以用 `;`、`|` 或换行分隔，例如：

```text
authors: Author A; Author B
topics: Intelligent tutoring systems; Adaptive learning
affiliations: University A; University B
```

兼容别名：

```text
title / paper_title
authors / author
journal / source / publication_source
year / publication_year
topics / keywords / theme
affiliations / institutions / author_units
citations / citation_count / cited_by
```

## 3. 图形编码

节点类型：

```text
author       作者
journal      期刊或来源
year         年份
topic        主题或关键词
affiliation  作者单位
```

视觉编码：

```text
节点颜色 -> 节点类型
节点大小 -> 该节点关联论文的引用量总和
边宽     -> 两个节点共现论文的引用量总和
边透明度 -> 共现次数
```

边的生成规则：

```text
author-author          同一篇论文中的共同作者
author-affiliation     作者与单位在同一篇论文中共现
author-journal         作者发表于某来源
author-topic           作者涉及某主题
author-year            作者活跃年份
journal-year           来源年份
topic-year             主题年份
affiliation-topic      单位与主题共现
```

## 4. 使用命令

生成 SVG 和 report：

```bash
mkdir -p outputs/figures

python3 tools/render_bibliometric_network.py \
  --input tools/examples/aied_bibliometric_network_records.json \
  --output outputs/figures/aied_bibliometric_network.svg \
  --report outputs/figures/aied_bibliometric_network.report.json \
  --title "Figure X. Bibliometric connection network"
```

转 PNG：

```bash
rsvg-convert \
  -o outputs/figures/aied_bibliometric_network.png \
  outputs/figures/aied_bibliometric_network.svg
```

只验证输入是否能生成图：

```bash
python3 tools/render_bibliometric_network.py \
  --input tools/examples/aied_bibliometric_network_records.json \
  --validate-only \
  --report outputs/figures/aied_bibliometric_network.report.json
```

查看内置示例数据：

```bash
python3 tools/render_bibliometric_network.py --dump-sample
```

## 5. 常用参数

```text
--max-nodes-per-type  每类节点最多保留多少个，默认 24
--min-node-citations  过滤低引用节点，默认 0
--max-labels          最多显示多少个标签，默认 48
--seed                固定布局随机种子，默认 20260710
--width               SVG 宽度，默认 1600
--height              SVG 高度，默认 1120
```

示例：只显示每类前 15 个高引用节点：

```bash
python3 tools/render_bibliometric_network.py \
  --input scraped_records.json \
  --output outputs/figures/network.svg \
  --report outputs/figures/network.report.json \
  --max-nodes-per-type 15 \
  --min-node-citations 20 \
  --max-labels 36
```

## 6. Report 检查

report 会输出：

```text
input_records
node_count
edge_count
nodes_by_type
top_nodes
warnings
overlap_checks
validation
style_contract
```

最小通过条件：

```text
validation.passed = true
validation.has_author_nodes = true
validation.has_topic_nodes = true
validation.has_affiliation_nodes = true
validation.overlap_checks_passed = true
```

`overlap_checks` 会检查生成后的几何结果：

```text
node_overlaps         节点圆之间是否互相压住
label_overlaps        文字标签之间是否重叠
label_bounds_issues   文字是否越出画布
label_node_overlaps   文字是否压到其他节点
```

如果某个标签无法在不重叠的位置显示，渲染器会自动跳过该标签，但节点仍保留在图中，详细数据仍可通过 SVG tooltip 和 report 查看。CLI 在 `validation.passed = false` 时返回非零退出码。

快速检查：

```bash
python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("outputs/figures/aied_bibliometric_network.report.json").read_text())
print(json.dumps(report["validation"], ensure_ascii=False, indent=2))
print(json.dumps(report["nodes_by_type"], ensure_ascii=False, indent=2))

assert report["validation"]["passed"]
assert report["validation"]["has_author_nodes"]
assert report["validation"]["has_topic_nodes"]
assert report["validation"]["has_affiliation_nodes"]
assert report["validation"]["overlap_checks_passed"]
PY
```

## 7. 在 CC 中调用

在 Claude Code 中可以这样描述任务：

```text
请使用 tools/render_bibliometric_network.py，把我爬取的 scraped_records.json 渲染成类似 Two Decades of Artificial Intelligence in Education 里 Figure 7/8 那种 bibliometric connection network。

要求：
1. authors、journal、year、topics、affiliations 都作为节点；
2. citations 作为节点大小和边宽的权重属性；
3. 输出 SVG、PNG 和 report；
4. report 里 validation 必须通过；
5. 如果字段缺失，只在 warnings 里说明，不要编造数据。
```

## 8. 注意事项

- 本模块适合几十到几百个聚合节点。数据量很大时，先用 `--max-nodes-per-type` 控制密度。
- 引用量为缺失或非数字时按 `0` 处理。
- 如果没有真实引用量，可以生成演示图，但必须在正文或图注中说明是示例数据。
- 如果需要国家/地区 collaboration network，可以把国家/地区放入 `affiliations` 或扩展一个新的 `country` 节点类型。
