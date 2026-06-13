#!/usr/bin/env python3
"""Semantic review-flow renderer: JSON IR -> template layout -> HTML/CSS -> SVG arrows -> Playwright."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
DEFAULT_SPEC_PATH = TOOLS_DIR / "examples" / "aied_figure1_spec.json"
PLAYWRIGHT_RENDERER = TOOLS_DIR / "render_html_playwright.mjs"


@dataclass
class Node:
    node_id: str
    role: str
    text: str
    stage: str | None = None
    lane: str = "left"


@dataclass
class Edge:
    source: str
    target: str
    kind: str
    route: str


@dataclass
class Box:
    box_id: str
    role: str
    text: str
    x: int
    y: int
    w: int
    h: int
    lane: str = "left"
    cls: str = "box"


def load_spec(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_ir(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("template") == "review_flow":
        return spec

    # Backward-compatible shim for the earlier hardcoded spec format.
    return {
        "template": "review_flow",
        "title": spec["title"],
        "stage_labels": spec["stage_labels"],
        "left_caption": spec["left_caption"],
        "right_caption": spec["right_caption"],
        "nodes": [
            {"id": "strategy1", "role": "source", "text": spec["strategy_boxes"][0]["text"], "stage": "identification"},
            {"id": "strategy2", "role": "source", "text": spec["strategy_boxes"][1]["text"], "stage": "identification"},
            {"id": "total", "role": "merge", "text": spec["total_box"], "stage": "screening"},
            {"id": "duplicate", "role": "branch_label", "text": spec["duplicate_label"], "stage": "screening"},
            {"id": "manual", "role": "trunk_step", "text": spec["manual_box"], "stage": "screening"},
            {"id": "excluded", "role": "branch_detail", "text": spec["excluded_box"], "stage": "screening"},
            {"id": "analysis", "role": "trunk_terminal", "text": spec["analysis_box"], "stage": "included"},
            {"id": "citation", "role": "support", "text": spec["citation_box"], "stage": "included"},
        ]
        + [
            {"id": f"step{index + 1}", "role": "analysis_step", "text": text, "lane": "right"}
            for index, text in enumerate(spec["analysis_steps"])
        ],
        "edges": [
            {"source": "strategy1", "target": "total", "kind": "arrow", "route": "merge"},
            {"source": "strategy2", "target": "total", "kind": "arrow", "route": "merge"},
            {"source": "total", "target": "duplicate", "kind": "line", "route": "branch_label"},
            {"source": "total", "target": "manual", "kind": "arrow", "route": "trunk"},
            {"source": "manual", "target": "excluded", "kind": "line", "route": "branch_detail"},
            {"source": "manual", "target": "analysis", "kind": "arrow", "route": "trunk"},
            {"source": "analysis", "target": "citation", "kind": "line", "route": "support"},
            {"source": "analysis", "target": "analysis_panel", "kind": "arrow", "route": "panel"},
        ],
    }


def parse_nodes(ir: dict[str, Any]) -> list[Node]:
    return [
        Node(
            node_id=item["id"],
            role=item["role"],
            text=item["text"],
            stage=item.get("stage"),
            lane=item.get("lane", "left"),
        )
        for item in ir["nodes"]
    ]


def parse_edges(ir: dict[str, Any]) -> list[Edge]:
    return [
        Edge(
            source=item["source"],
            target=item["target"],
            kind=item["kind"],
            route=item["route"],
        )
        for item in ir["edges"]
    ]


def validate_ir(ir: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if ir.get("template") != "review_flow":
        issues.append("unsupported template")
        return issues

    nodes = parse_nodes(ir)
    edges = parse_edges(ir)
    node_map = {node.node_id: node for node in nodes}

    required_roles = {
        "source": 2,
        "merge": 1,
        "branch_label": 1,
        "trunk_step": 1,
        "branch_detail": 1,
        "trunk_terminal": 1,
        "support": 1,
    }
    for role, count in required_roles.items():
        found = [node for node in nodes if node.role == role]
        if len(found) != count:
            issues.append(f"role count mismatch: {role} expected {count}, got {len(found)}")

    analysis_steps = [node for node in nodes if node.role == "analysis_step"]
    if len(analysis_steps) < 1:
        issues.append("missing analysis steps")

    for edge in edges:
        if edge.source not in node_map:
            issues.append(f"unknown edge source: {edge.source}")
        if edge.target != "analysis_panel" and edge.target not in node_map:
            issues.append(f"unknown edge target: {edge.target}")

    merge = next((node for node in nodes if node.role == "merge"), None)
    trunk_step = next((node for node in nodes if node.role == "trunk_step"), None)
    terminal = next((node for node in nodes if node.role == "trunk_terminal"), None)
    branch_label = next((node for node in nodes if node.role == "branch_label"), None)
    branch_detail = next((node for node in nodes if node.role == "branch_detail"), None)
    support = next((node for node in nodes if node.role == "support"), None)

    def has_edge(source: str, target: str, route: str) -> bool:
        return any(edge.source == source and edge.target == target and edge.route == route for edge in edges)

    if merge and trunk_step and not has_edge(merge.node_id, trunk_step.node_id, "trunk"):
        issues.append("main trunk missing merge -> trunk_step")
    if trunk_step and terminal and not has_edge(trunk_step.node_id, terminal.node_id, "trunk"):
        issues.append("main trunk missing trunk_step -> trunk_terminal")
    if merge and branch_label and not has_edge(merge.node_id, branch_label.node_id, "branch_label"):
        issues.append("missing merge -> branch_label branch")
    if trunk_step and branch_detail and not has_edge(trunk_step.node_id, branch_detail.node_id, "branch_detail"):
        issues.append("missing trunk_step -> branch_detail branch")
    if terminal and support and not has_edge(terminal.node_id, support.node_id, "support"):
        issues.append("missing trunk_terminal -> support")
    if terminal and not has_edge(terminal.node_id, "analysis_panel", "panel"):
        issues.append("missing trunk_terminal -> analysis_panel")

    for source in [node for node in nodes if node.role == "source"]:
        if merge and not has_edge(source.node_id, merge.node_id, "merge"):
            issues.append(f"missing source merge edge: {source.node_id} -> {merge.node_id}")

    return issues


def build_layout(ir: dict[str, Any]) -> dict[str, Any]:
    nodes = parse_nodes(ir)
    node_map = {node.node_id: node for node in nodes}
    left_nodes = [node for node in nodes if node.lane != "right"]
    right_steps = [node for node in nodes if node.role == "analysis_step"]

    role_box = {
        "source": (0, 0, 270, 200),
        "merge": (0, 0, 220, 132),
        "branch_label": (0, 0, 280, 46),
        "trunk_step": (0, 0, 230, 110),
        "branch_detail": (0, 0, 320, 300),
        "trunk_terminal": (0, 0, 230, 96),
        "support": (0, 0, 320, 96),
        "analysis_step": (0, 0, 280, 96),
    }

    source_nodes = [node for node in left_nodes if node.role == "source"]
    merge_node = next(node for node in left_nodes if node.role == "merge")
    branch_label = next(node for node in left_nodes if node.role == "branch_label")
    trunk_step = next(node for node in left_nodes if node.role == "trunk_step")
    branch_detail = next(node for node in left_nodes if node.role == "branch_detail")
    terminal = next(node for node in left_nodes if node.role == "trunk_terminal")
    support = next(node for node in left_nodes if node.role == "support")

    boxes = [
        Box(source_nodes[0].node_id, source_nodes[0].role, source_nodes[0].text, 125, 135, 270, 200),
        Box(source_nodes[1].node_id, source_nodes[1].role, source_nodes[1].text, 425, 135, 320, 200),
        Box(merge_node.node_id, merge_node.role, merge_node.text, 320, 395, 220, 132),
        Box(branch_label.node_id, branch_label.role, branch_label.text, 660, 458, 280, 46),
        Box(trunk_step.node_id, trunk_step.role, trunk_step.text, 315, 610, 230, 110),
        Box(branch_detail.node_id, branch_detail.role, branch_detail.text, 660, 600, 320, 300),
        Box(terminal.node_id, terminal.role, terminal.text, 315, 1010, 230, 96),
        Box(support.node_id, support.role, support.text, 660, 1010, 320, 96),
    ]

    step_y = [360, 470, 625, 775]
    step_h = [90, 110, 90, 110]
    for index, node in enumerate(right_steps[:4]):
        boxes.append(
            Box(node.node_id, node.role, node.text, 1350, step_y[index], 280, step_h[index], "right")
        )

    return {
        "canvas_width": 1800,
        "canvas_height": 1280,
        "left_panel": {"x": 60, "y": 80, "w": 1110, "h": 1095},
        "right_panel": {"x": 1305, "y": 335, "w": 400, "h": 565},
        "stage_labels": [
            {"text": ir["stage_labels"][0], "x": 70, "y": 190},
            {"text": ir["stage_labels"][1], "x": 70, "y": 515},
            {"text": ir["stage_labels"][2], "x": 70, "y": 835},
        ],
        "left_caption": {"text": ir["left_caption"], "x": 470, "y": 1125},
        "right_caption": {"text": ir["right_caption"], "x": 1505, "y": 960},
        "boxes": boxes,
        "node_roles": {node.node_id: node.role for node in nodes},
        "edges": [edge.__dict__ for edge in parse_edges(ir)],
    }


def box_map(layout: dict[str, Any]) -> dict[str, Box]:
    return {box.box_id: box for box in layout["boxes"]}


def p(x: float, y: float) -> str:
    return f"{x:.1f},{y:.1f}"


def arrow_svg(layout: dict[str, Any]) -> str:
    boxes = box_map(layout)
    edges = layout["edges"]
    right = layout["right_panel"]

    source_boxes = [boxes[edge["source"]] for edge in edges if edge["route"] == "merge"]
    merge = next(boxes[edge["target"]] for edge in edges if edge["route"] == "merge")
    trunk_step = next(boxes[edge["target"]] for edge in edges if edge["route"] == "trunk" and boxes[edge["target"]].role == "trunk_step")
    terminal = next(boxes[edge["target"]] for edge in edges if edge["route"] == "trunk" and boxes[edge["target"]].role == "trunk_terminal")
    branch_label = next(boxes[edge["target"]] for edge in edges if edge["route"] == "branch_label")
    branch_detail = next(boxes[edge["target"]] for edge in edges if edge["route"] == "branch_detail")
    support = next(boxes[edge["target"]] for edge in edges if edge["route"] == "support")

    merge_y = 358
    trunk_x = merge.x + merge.w / 2
    line_y_dup = branch_label.y + branch_label.h / 2
    line_y_ex = trunk_step.y + trunk_step.h + 74
    arrow_right_y = 680
    support_y = terminal.y + terminal.h / 2

    merge_lines = []
    for source in source_boxes:
        merge_lines.append(
            f'<polyline points="{p(source.x + source.w / 2, source.y + source.h)} {p(source.x + source.w / 2, merge_y)} {p(trunk_x, merge_y)}" '
            'fill="none" stroke="#b2ccee" stroke-width="2.0"/>'
        )

    return f"""
<svg class="arrow-layer" viewBox="0 0 {layout['canvas_width']} {layout['canvas_height']}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrowHead" markerWidth="9" markerHeight="7" refX="7" refY="3.5" orient="auto">
      <polygon points="0,0 9,3.5 0,7" fill="#9bbbe8"></polygon>
    </marker>
  </defs>
  {''.join(merge_lines)}
  <line x1="{trunk_x}" y1="{merge_y}" x2="{trunk_x}" y2="{merge.y}"
    stroke="#b2ccee" stroke-width="2.0" marker-end="url(#arrowHead)"/>
  <line x1="{trunk_x}" y1="{merge.y + merge.h}" x2="{trunk_x}" y2="{trunk_step.y}"
    stroke="#b2ccee" stroke-width="2.0" marker-end="url(#arrowHead)"/>
  <line x1="{trunk_x}" y1="{merge.y + merge.h}" x2="{trunk_x}" y2="{line_y_dup}"
    stroke="#b2ccee" stroke-width="2.0"/>
  <line x1="{trunk_x}" y1="{line_y_dup}" x2="{branch_label.x}" y2="{line_y_dup}"
    stroke="#b2ccee" stroke-width="2.0"/>
  <line x1="{trunk_x}" y1="{trunk_step.y + trunk_step.h}" x2="{trunk_x}" y2="{terminal.y}"
    stroke="#b2ccee" stroke-width="2.0" marker-end="url(#arrowHead)"/>
  <line x1="{trunk_x}" y1="{line_y_ex}" x2="{branch_detail.x}" y2="{line_y_ex}"
    stroke="#b2ccee" stroke-width="2.0"/>
  <line x1="{terminal.x + terminal.w}" y1="{support_y}" x2="{support.x}" y2="{support_y}"
    stroke="#b2ccee" stroke-width="2.0"/>
  <polygon points="{p(1170, arrow_right_y - 18)} {p(right['x'] - 48, arrow_right_y - 18)} {p(right['x'] - 48, arrow_right_y - 36)} {p(right['x'], arrow_right_y)} {p(right['x'] - 48, arrow_right_y + 36)} {p(right['x'] - 48, arrow_right_y + 18)} {p(1170, arrow_right_y + 18)}"
    fill="#9bbbe8"/>
</svg>
"""


def html_for_layout(ir: dict[str, Any], layout: dict[str, Any]) -> str:
    box_html = []
    for box in layout["boxes"]:
        box_html.append(
            f'<div class="{box.cls}" data-box-id="{box.box_id}" data-box-role="{box.role}" '
            f'style="left:{box.x}px;top:{box.y}px;width:{box.w}px;height:{box.h}px;">'
            f'<div class="box-text">{box.text.replace(chr(10), "<br/>")}</div></div>'
        )

    stage_html = []
    for item in layout["stage_labels"]:
        stage_html.append(
            f'<div class="stage-label" data-stage-label="{item["text"]}" '
            f'style="left:{item["x"]}px;top:{item["y"]}px;">{item["text"]}</div>'
        )

    left_panel = layout["left_panel"]
    right_panel = layout["right_panel"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{ir['title']}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #ffffff;
      font-family: "Georgia", "Times New Roman", "Microsoft YaHei", serif;
    }}
    .figure-canvas {{
      position: relative;
      width: {layout['canvas_width']}px;
      height: {layout['canvas_height']}px;
      margin: 0 auto;
      background: #ffffff;
      color: #1f2e4f;
    }}
    .title {{
      position: absolute;
      top: 16px;
      left: 0;
      width: 100%;
      text-align: center;
      font-size: 28px;
      font-weight: 700;
      font-style: italic;
    }}
    .panel {{
      position: absolute;
      border: 2px dashed #9fc5ff;
      border-radius: 6px;
      background: rgba(255,255,255,0.18);
    }}
    .stage-label {{
      position: absolute;
      width: 42px;
      height: 170px;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 8px 6px;
      border: 2px solid #8cb6ea;
      border-radius: 16px;
      background: rgba(196, 220, 250, 0.95);
      writing-mode: vertical-rl;
      transform: rotate(180deg);
      text-align: center;
      font-size: 20px;
      font-weight: 700;
      color: #3d67b1;
      z-index: 3;
    }}
    .box {{
      position: absolute;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 8px 12px;
      border: 2px solid #5a8cff;
      border-radius: 0;
      background: rgba(255,255,255,0.95);
      text-align: center;
      z-index: 2;
    }}
    .box-text {{
      width: 100%;
      max-height: 100%;
      overflow: hidden;
      line-height: 1.24;
      font-size: 13px;
      color: #24344f;
    }}
    .arrow-layer {{
      position: absolute;
      inset: 0;
      z-index: 1;
      overflow: visible;
    }}
    .left-caption {{
      position: absolute;
      left: {layout['left_caption']['x'] - 250}px;
      top: {layout['left_caption']['y']}px;
      width: 500px;
      text-align: center;
      font-size: 18px;
      font-weight: 700;
      font-style: italic;
      color: #24344f;
    }}
    .right-caption {{
      position: absolute;
      left: {layout['right_caption']['x'] - 245}px;
      top: {layout['right_caption']['y']}px;
      width: 490px;
      text-align: center;
      font-size: 17px;
      font-weight: 700;
      font-style: italic;
      line-height: 1.35;
      color: #24344f;
    }}
  </style>
</head>
<body>
  <div class="figure-canvas" data-template="{ir['template']}">
    <div class="title">{ir['title']}</div>
    <div class="panel" style="left:{left_panel['x']}px;top:{left_panel['y']}px;width:{left_panel['w']}px;height:{left_panel['h']}px;"></div>
    <div class="panel" style="left:{right_panel['x']}px;top:{right_panel['y']}px;width:{right_panel['w']}px;height:{right_panel['h']}px;"></div>
    {''.join(stage_html)}
    {arrow_svg(layout)}
    {''.join(box_html)}
    <div class="left-caption">{ir['left_caption']}</div>
    <div class="right-caption">{ir['right_caption']}</div>
  </div>
</body>
</html>
"""


def run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render semantic review-flow diagrams through HTML/CSS + Playwright.")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--output-html", type=Path, default=ROOT / "outputs" / "figures" / "aied_figure1_playwright.html")
    parser.add_argument("--report", type=Path, default=ROOT / "outputs" / "figures" / "aied_figure1_playwright.report.json")
    parser.add_argument("--dump-ir", action="store_true")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    ir = build_ir(spec)
    logic_issues = validate_ir(ir)
    if args.dump_ir:
        print(json.dumps(ir, ensure_ascii=False, indent=2))
        return 0
    if logic_issues:
        raise SystemExit("IR validation failed:\n- " + "\n- ".join(logic_issues))

    layout = build_layout(ir)
    html = html_for_layout(ir, layout)

    args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.output_html.write_text(html, encoding="utf-8")

    run(["npm", "install"], cwd=TOOLS_DIR)

    png_path = args.output_html.with_suffix(".png")
    pdf_path = args.output_html.with_suffix(".pdf")
    run(
        [
            "node",
            str(PLAYWRIGHT_RENDERER),
            str(args.output_html),
            str(png_path),
            str(pdf_path),
            str(args.report),
        ]
    )

    raw_checks = json.loads(args.report.read_text(encoding="utf-8"))
    final_report = {
        "pipeline": [
            "semantic_json_ir",
            "logic_validation",
            "template_layout",
            "html_css_typesetting",
            "svg_arrow_layer",
            "playwright_export",
            "geometry_boundary_check",
        ],
        "ir": ir,
        "logic_checks": {
            "passed": len(logic_issues) == 0,
            "issues": logic_issues,
        },
        "layout": {
            "canvas_width": layout["canvas_width"],
            "canvas_height": layout["canvas_height"],
            "box_count": len(layout["boxes"]),
        },
        "files": {
            "html": str(args.output_html.resolve()),
            "png": str(png_path.resolve()),
            "pdf": str(pdf_path.resolve()),
            "report": str(args.report.resolve()),
        },
        "playwright_checks": raw_checks,
    }
    args.report.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HTML={args.output_html.resolve()}")
    print(f"PNG={png_path.resolve()}")
    print(f"PDF={pdf_path.resolve()}")
    print(f"REPORT={args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
