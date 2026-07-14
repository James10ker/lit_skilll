# 安装说明

## Claude Code / Codex 类 Agent

把整个目录复制到 skills 目录，目录名与 `SKILL.md` 中的 `name: literature-review-skill` 保持一致。

```bash
mkdir -p .claude/skills
cp -a literature-review-skill .claude/skills/literature-review-skill
```

## Cursor

可放到：

- Windows: `%USERPROFILE%\.cursor\skills\literature-review-skill\`
- macOS / Linux: `~/.cursor/skills/literature-review-skill/`

重启后在 Settings / Rules 或技能列表中确认可发现。

## 依赖

基础依赖：

```bash
pip install -r requirements.txt
```

可选用途：

- `docx_to_md.py`: Word 转 Markdown
- `pptx_to_md.py`: PowerPoint 转 Markdown
- Office/Markdown 格式转换（仅作为输入兼容或用户明确要求的附加输出）

Mermaid 图渲染需要 Node.js：

```bash
cd tools
npm install
```

核心年度图、词云和 LaTeX 静态门禁只依赖 Python 标准库。生成 PNG 需安装 `rsvg-convert`；编译最终稿建议安装 XeLaTeX 或 `latexmk`。
