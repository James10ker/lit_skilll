#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

function resolveChromePath() {
  return (
    process.env.PLAYWRIGHT_CHROME_PATH ||
    "/usr/bin/google-chrome-stable"
  );
}

async function main() {
  const [, , htmlPath, pngPath, pdfPath, reportPath] = process.argv;
  if (!htmlPath || !pngPath || !pdfPath || !reportPath) {
    console.error(
      "usage: node render_html_playwright.mjs <input.html> <output.png> <output.pdf> <report.json>",
    );
    process.exit(1);
  }

  const browser = await chromium.launch({
    executablePath: resolveChromePath(),
    headless: true,
  });

  const page = await browser.newPage({
    viewport: { width: 1800, height: 1280 },
    deviceScaleFactor: 2,
  });

  const fileUrl = `file://${path.resolve(htmlPath)}`;
  await page.goto(fileUrl, { waitUntil: "load" });
  await page.waitForTimeout(150);

  const metrics = await page.evaluate(() => {
    const canvas = document.querySelector(".figure-canvas");
    const boxes = [...document.querySelectorAll("[data-box-id]")];
    const stageLabels = [...document.querySelectorAll("[data-stage-label]")];
    const issues = [];
    const overflow = [];
    const overlap = [];
    const stageOverlap = [];
    const canvasRect = canvas?.getBoundingClientRect();

    const boxRects = boxes.map((el) => {
      const rect = el.getBoundingClientRect();
      const inner = el.querySelector(".box-text");
      if (inner && inner.scrollHeight - inner.clientHeight > 2) {
        overflow.push(el.getAttribute("data-box-id"));
        issues.push(`text overflow: ${el.getAttribute("data-box-id")}`);
      }
      if (canvasRect) {
        if (rect.left < canvasRect.left - 1 || rect.right > canvasRect.right + 1) {
          issues.push(`box out of canvas x: ${el.getAttribute("data-box-id")}`);
        }
        if (rect.top < canvasRect.top - 1 || rect.bottom > canvasRect.bottom + 1) {
          issues.push(`box out of canvas y: ${el.getAttribute("data-box-id")}`);
        }
      }
      return {
        id: el.getAttribute("data-box-id"),
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
      };
    });

    for (let i = 0; i < boxRects.length; i += 1) {
      for (let j = i + 1; j < boxRects.length; j += 1) {
        const a = boxRects[i];
        const b = boxRects[j];
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ox > 3 && oy > 3) {
          overlap.push([a.id, b.id]);
          issues.push(`overlap: ${a.id} / ${b.id}`);
        }
      }
    }

    const stageRects = stageLabels.map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        id: el.getAttribute("data-stage-label"),
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
      };
    });

    for (const stage of stageRects) {
      for (const box of boxRects) {
        const ox = Math.min(stage.right, box.right) - Math.max(stage.left, box.left);
        const oy = Math.min(stage.bottom, box.bottom) - Math.max(stage.top, box.top);
        if (ox > 3 && oy > 3) {
          stageOverlap.push([stage.id, box.id]);
          issues.push(`stage overlap: ${stage.id} / ${box.id}`);
        }
      }
    }

    const bbox = canvasRect
      ? {
          left: canvasRect.left,
          top: canvasRect.top,
          right: canvasRect.right,
          bottom: canvasRect.bottom,
          width: canvasRect.width,
          height: canvasRect.height,
        }
      : null;

    return {
      passed: issues.length === 0,
      issues,
      overflow,
      overlap,
      stageOverlap,
      bbox,
      boxCount: boxRects.length,
    };
  });

  await page.screenshot({
    path: pngPath,
    fullPage: true,
  });

  await page.pdf({
    path: pdfPath,
    printBackground: true,
    width: "1800px",
    height: "1280px",
    margin: { top: "0", right: "0", bottom: "0", left: "0" },
  });

  await fs.writeFile(reportPath, JSON.stringify(metrics, null, 2), "utf8");
  await browser.close();
  console.log(`PNG=${path.resolve(pngPath)}`);
  console.log(`PDF=${path.resolve(pdfPath)}`);
  console.log(`REPORT=${path.resolve(reportPath)}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
