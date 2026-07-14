# 迭代上下文判断

当用户基于已有综述继续工作时，先判断意图：

- 新增文献、补材料、扩写章节、合并笔记：使用 `merger.md`
- 修正事实、引用、观点归属、结构错误、风格不符：使用 `correction_handler.md`
- 如果两类都存在，先纠错再合并新增内容。

## 版本规则

除非用户明确要求覆盖，每轮修订使用独立版本目录，例如：

`outputs/{主题标识}/versions/{YYYYMMDDHHmmss}/review.tex`

同步保留该版本的 `.bib`、figures、data 和 reports；修订后重新执行全部质量门禁。

## 记录

对重要修订保留简短修订记录，可追加到同目录：

`revision_log.txt`
