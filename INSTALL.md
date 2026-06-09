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

用途：

- `docx_to_md.py`: Word 转 Markdown
- `pptx_to_md.py`: PowerPoint 转 Markdown
- `md_to_docx.py`: Markdown 转 Word

Mermaid 图渲染需要 Node.js：

```bash
cd tools
npm install
```

若只使用纯 Markdown 输出，可不安装 Node 依赖。
