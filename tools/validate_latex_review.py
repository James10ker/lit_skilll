#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SECTION_ALIASES = {
    "introduction": {"introduction", "background", "overview", "引言", "绪论", "研究背景"},
    "methods": {
        "methods",
        "method",
        "methodology",
        "materials and methods",
        "dataset and methods",
        "data and methods",
        "datasets and methods",
        "data sources and methods",
        "review methods",
        "search strategy",
        "方法",
        "研究方法",
        "数据与方法",
        "数据来源与方法",
        "文献检索与筛选方法",
    },
    "results": {"results", "findings", "review results", "synthesis", "evidence synthesis", "结果", "研究结果", "综述结果", "证据综合"},
    "discussion": {"discussion", "implications", "discussion and implications", "讨论", "讨论与启示"},
    "conclusion": {"conclusion", "conclusions", "summary and conclusions", "结论", "总结与展望"},
}

IMAGE_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")
PROMPT_TRACE_PATTERNS = (
    (re.compile(r"```"), "Markdown fenced code block marker"),
    (re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"), "Markdown heading marker"),
    (re.compile(r"\b(as an ai|chatgpt|large language model)\b", re.I), "AI assistant trace"),
    (re.compile(r"\b(prompt|instruction|user request)\s*:", re.I), "prompt trace label"),
)
PLACEHOLDER_PATTERNS = (
    (re.compile(r"\b(TODO|FIXME|XXX|TBD|TK)\b", re.I), "placeholder token"),
    (re.compile(r"\blorem ipsum\b", re.I), "placeholder prose"),
    (re.compile(r"\[(?:insert|add|todo|placeholder|citation needed)[^\]]*\]", re.I), "bracketed placeholder"),
    (re.compile(r"<(?:insert|add|todo|placeholder)[^>]*>", re.I), "angle-bracket placeholder"),
    (re.compile(r"\\(?:todo|missing|placeholder)\s*\{[^}]*\}", re.I), "LaTeX placeholder command"),
    (re.compile(r"\?\?+"), "unresolved question-mark placeholder"),
)


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    metrics: dict[str, object]

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


def _strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        cut_at = None
        for match in re.finditer("%", line):
            backslashes = 0
            index = match.start() - 1
            while index >= 0 and line[index] == "\\":
                backslashes += 1
                index -= 1
            if backslashes % 2 == 0:
                cut_at = match.start()
                break
        lines.append(line[:cut_at] if cut_at is not None else line)
    return "\n".join(lines)


def _normalize_heading(value: str) -> str:
    value = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", r"\1", value)
    value = re.sub(r"[^a-zA-Z0-9\u3400-\u9fff& ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    value = value.replace("&", "and")
    return value


def _section_headings(text: str) -> list[str]:
    pattern = re.compile(r"\\(?:section|chapter)\*?(?:\[[^\]]*\])?\{([^{}]+)\}")
    return [_normalize_heading(match.group(1)) for match in pattern.finditer(text)]


def _find_sections(headings: Iterable[str]) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for required, aliases in SECTION_ALIASES.items():
        found[required] = next((heading for heading in headings if heading in aliases), None)
    return found


def _has_keywords(text: str) -> bool:
    return bool(
        re.search(r"\\(?:keywords?|IEEEkeywords)\s*\{[^{}]+\}", text, re.I)
        or re.search(r"\\begin\{(?:keywords|IEEEkeywords)\}.*?\\end\{(?:keywords|IEEEkeywords)\}", text, re.I | re.S)
        or re.search(r"(?mi)^\s*\\?noindent\s*\{?\\?bfseries\s+Keywords\b", text)
        or re.search(r"(?mi)^\s*(?:Keywords|关键词)\s*[:：\-]", text)
        or re.search(r"\\(?:textbf|bfseries)\s*\{?关键词\}?", text)
    )


def _word_count(text: str) -> tuple[int, int, int]:
    text = re.sub(r"\\(?:begin|end)\{[^}]+\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}$^_~&]", " ", text)
    latin_words = len(re.findall(r"\b[A-Za-z][A-Za-z0-9'-]*\b", text))
    cjk_characters = len(re.findall(r"[\u3400-\u9fff]", text))
    effective_words = latin_words + math.ceil(cjk_characters / 2)
    return effective_words, latin_words, cjk_characters


def _resolve_graphic(path_value: str, base_dir: Path) -> Path | None:
    if "\\" in path_value or "{" in path_value or "}" in path_value:
        return None
    raw = Path(path_value)
    candidates = [raw] if raw.suffix else [raw, *(Path(str(raw) + ext) for ext in IMAGE_EXTENSIONS)]
    for candidate in candidates:
        full = candidate if candidate.is_absolute() else base_dir / candidate
        if full.exists():
            return full
    return None


def _extract_environment_blocks(text: str, names: Iterable[str]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for name in names:
        pattern = re.compile(rf"\\begin\{{{name}\}}(.*?)\\end\{{{name}\}}", re.S)
        blocks.extend((name, match.group(1)) for match in pattern.finditer(text))
    return blocks


def _extract_bibliography_files(text: str, base_dir: Path) -> list[Path]:
    bibs: list[Path] = []
    for command in ("bibliography", "addbibresource"):
        for match in re.finditer(rf"\\{command}(?:\[[^\]]*\])?\{{([^}}]+)\}}", text):
            for raw_name in match.group(1).split(","):
                name = raw_name.strip()
                if not name:
                    continue
                path = Path(name)
                if path.suffix.lower() != ".bib":
                    path = Path(f"{name}.bib")
                bibs.append(path if path.is_absolute() else base_dir / path)
    return bibs


def _bibliography_keys(text: str, base_dir: Path, warnings: list[str]) -> set[str]:
    keys = set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", text))
    for bib_path in _extract_bibliography_files(text, base_dir):
        if not bib_path.exists():
            warnings.append(f"Referenced bibliography file does not exist: {bib_path}")
            continue
        try:
            bib_text = bib_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            bib_text = bib_path.read_text(encoding="latin-1")
        keys.update(match.group(1).strip() for match in re.finditer(r"@\w+\s*\{\s*([^,\s]+)", bib_text))
    return keys


def _citation_keys(text: str) -> set[str]:
    keys: set[str] = set()
    cite_pattern = re.compile(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|autocite|parencite|textcite)\*?(?:\[[^\]]*\]){0,2}\{([^}]+)\}")
    for match in cite_pattern.finditer(text):
        keys.update(key.strip() for key in match.group(1).split(",") if key.strip())
    return keys


def validate_latex_review(input_path: Path, min_words: int = 0, min_figures: int = 0) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    path = input_path.resolve()
    base_dir = path.parent

    try:
        raw_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw_text = path.read_text(encoding="latin-1")
    text = _strip_comments(raw_text)

    if not re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", text):
        errors.append("Missing LaTeX documentclass declaration.")
    if "\\begin{document}" not in text:
        errors.append("Missing \\begin{document}.")
    if "\\end{document}" not in text:
        errors.append("Missing \\end{document}.")

    if not re.search(r"\\title(?:\[[^\]]*\])?\{[^{}]+\}", text, re.S):
        errors.append("Missing non-empty \\title{...}.")
    if not re.search(r"\\begin\{abstract\}.*?\\end\{abstract\}", text, re.S):
        errors.append("Missing abstract environment.")
    if not _has_keywords(text):
        errors.append("Missing keywords.")

    headings = _section_headings(text)
    found_sections = _find_sections(headings)
    for required, matched in found_sections.items():
        if matched is None:
            alias_list = ", ".join(sorted(SECTION_ALIASES[required]))
            errors.append(f"Missing required {required} section; accepted aliases: {alias_list}.")

    for pattern, label in PROMPT_TRACE_PATTERNS:
        if pattern.search(text):
            errors.append(f"Found {label}.")
    for pattern, label in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            errors.append(f"Found unresolved {label}.")

    graphics = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text)
    missing_graphics = []
    for graphic in graphics:
        if _resolve_graphic(graphic.strip(), base_dir) is None:
            missing_graphics.append(graphic.strip())
    for graphic in missing_graphics:
        errors.append(f"includegraphics path does not exist: {graphic}")

    figure_table_blocks = _extract_environment_blocks(text, ("figure", "figure*", "table", "table*"))
    for index, (env_name, block) in enumerate(figure_table_blocks, start=1):
        has_caption = bool(re.search(r"\\caption(?:\[[^\]]*\])?\{", block))
        has_label = bool(re.search(r"\\label\{[^}]+\}", block))
        if has_caption != has_label:
            missing = "label" if has_caption else "caption"
            errors.append(f"{env_name} environment #{index} has a caption/label pairing issue: missing {missing}.")

    citation_keys = _citation_keys(text)
    bibliography_keys = _bibliography_keys(text, base_dir, warnings)
    unresolved = sorted(citation_keys - bibliography_keys)
    if citation_keys and not bibliography_keys:
        errors.append("Citations are present but no resolvable thebibliography entries or .bib keys were found.")
    for key in unresolved:
        errors.append(f"Citation key is unresolved: {key}")

    words, latin_words, cjk_characters = _word_count(text)
    figure_count = len(re.findall(r"\\begin\{figure\*?\}", text))
    if min_words and words < min_words:
        errors.append(f"Word count {words} is below minimum {min_words}.")
    if min_figures and figure_count < min_figures:
        errors.append(f"Figure count {figure_count} is below minimum {min_figures}.")

    metrics: dict[str, object] = {
        "word_count": words,
        "latin_word_count": latin_words,
        "cjk_character_count": cjk_characters,
        "figure_count": figure_count,
        "includegraphics_count": len(graphics),
        "missing_includegraphics_count": len(missing_graphics),
        "citation_count": len(citation_keys),
        "resolved_citation_count": len(citation_keys) - len(unresolved),
        "bibliography_key_count": len(bibliography_keys),
        "section_headings": headings,
        "required_sections": found_sections,
    }
    return ValidationResult(errors=errors, warnings=warnings, metrics=metrics)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a LaTeX literature-review artifact.")
    parser.add_argument("--input", required=True, type=Path, help="Path to the .tex file to validate.")
    parser.add_argument("--report", required=True, type=Path, help="Path to write the JSON validation report.")
    parser.add_argument("--min-words", type=int, default=0, help="Minimum acceptable word count.")
    parser.add_argument("--min-figures", type=int, default=0, help="Minimum acceptable figure count.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    result = validate_latex_review(args.input, min_words=args.min_words, min_figures=args.min_figures)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
