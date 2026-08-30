#!/usr/bin/env node
// Drives the SPA at $APP_URL (default http://localhost:5173) with
// Playwright and either takes one screenshot or walks a fixed demo
// interaction, saving a PNG per step plus an animated GIF stitched
// from those PNGs with gifenc (no ffmpeg dependency).
//
// Usage:
//   node driver.mjs shot <out.png>
//   node driver.mjs record <out-dir> [gif-name]
import { chromium } from "playwright";
import gifenc from "gifenc";
const { GIFEncoder, quantize, applyPalette } = gifenc;
import { PNG } from "pngjs";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP_URL = process.env.APP_URL ?? "http://localhost:5173";
const [, , cmd, ...args] = process.argv;

async function withPage(fn) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await fn(page);
  } finally {
    await browser.close();
  }
}

async function openApp(page) {
  await page.goto(APP_URL, { waitUntil: "networkidle" });
  await page.waitForSelector("text=Company A", { timeout: 10000 });
}

async function shot(outPath) {
  mkdirSync(path.dirname(outPath), { recursive: true });
  await withPage(async (page) => {
    await openApp(page);
    await page.screenshot({ path: outPath });
  });
  console.log(`wrote ${outPath}`);
}

// One representative flow: land on the app, open Company A's submission
// history, expand the batch, open a file's report, close it. Six frames
// that show the actual data surfaces a frontend PR is likely to touch.
async function record(outDir, gifName = "demo") {
  mkdirSync(outDir, { recursive: true });
  const frames = [];

  await withPage(async (page) => {
    try {
      await openApp(page);
      frames.push(await page.screenshot());

      await page.getByRole("button", { name: /History/ }).first().click();
      await page.waitForSelector("text=/files$/");
      frames.push(await page.screenshot());

      await page.getByText(/files$/).first().click();
      await page.waitForSelector("text=q3_expenses.csv");
      frames.push(await page.screenshot());

      await page.getByText("q3_expenses.csv").click();
      await page.waitForSelector('[role="dialog"]');
      await page.waitForSelector("text=Duplicate line item");
      frames.push(await page.screenshot());
      frames.push(await page.screenshot());

      await page.getByLabel("Close").click();
      await page.waitForSelector('[role="dialog"]', { state: "detached" });
      frames.push(await page.screenshot());
    } catch (err) {
      // Record whatever the page shows (including a crashed/blank state) so
      // "before" still produces a gif when the demo flow can't complete —
      // that failure is often exactly what the before/after is meant to show.
      console.error(`record: interaction stopped early (${err.message.split("\n")[0]})`);
      frames.push(await page.screenshot());
    }
  });

  frames.forEach((buf, i) => {
    writeFileSync(path.join(outDir, `frame-${String(i).padStart(2, "0")}.png`), buf);
  });

  const gifPath = path.join(outDir, `${gifName}.gif`);
  encodeGif(frames, gifPath);
  console.log(`wrote ${frames.length} frames and ${gifPath}`);
}

function encodeGif(pngBuffers, outPath) {
  const decoded = pngBuffers.map((buf) => PNG.sync.read(buf));
  const { width, height } = decoded[0];
  const gif = GIFEncoder();

  decoded.forEach((png, i) => {
    const rgba = png.data; // already RGBA
    const palette = quantize(rgba, 256);
    const index = applyPalette(rgba, palette);
    // hold each frame ~900ms, except the report-drawer frame held longer
    const delay = i === decoded.length - 2 ? 1800 : 900;
    gif.writeFrame(index, width, height, { palette, delay });
  });

  gif.finish();
  writeFileSync(outPath, gif.bytesView());
}

if (cmd === "shot") {
  await shot(args[0] ?? "screenshot.png");
} else if (cmd === "record") {
  await record(args[0] ?? "recording", args[1]);
} else {
  console.error("usage: node driver.mjs shot <out.png> | record <out-dir> [gif-name]");
  process.exit(1);
}
