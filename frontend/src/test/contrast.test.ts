/**
 * Phase 13: colour contrast of the design tokens, light and dark, against WCAG 2.2 AA.
 *
 * axe cannot measure contrast in jsdom (there is no layout or paint), so the tokens are checked
 * directly: every text colour on every background it is used on (4.5:1), and the borders, focus
 * rings and status marks people need to see (3:1, WCAG 1.4.11). Translucent tints are blended onto
 * the surface they sit on first. A failing pair names the theme, the colours and the ratio.
 */
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// The tests run from the frontend folder (npm scripts and CI). Not a "?raw" import: the test
// config turns CSS processing off, which empties it.
const css = readFileSync(join(process.cwd(), "src", "index.css"), "utf-8");

type Rgba = [number, number, number, number];

function tokens(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  const block = css.slice(start, css.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const [, name = "", value = ""] of block.matchAll(/--c-([\w-]+):\s*([^;]+);/g)) out[name] = value.trim();
  return out;
}

function parse(value: string): Rgba {
  const hex = /^#([0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const n = parseInt(hex[1] ?? "", 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
  }
  const rgb = /^rgb\((\d+) (\d+) (\d+)(?: \/ ([\d.]+))?\)$/.exec(value);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3]), rgb[4] ? Number(rgb[4]) : 1];
  throw new Error(`Unreadable colour ${value}`);
}

/** A translucent colour as it shows on an opaque surface. */
function over(top: Rgba, base: Rgba): Rgba {
  const a = top[3];
  const mix = (i: 0 | 1 | 2) => top[i] * a + base[i] * (1 - a);
  return [mix(0), mix(1), mix(2), 1];
}

function luminance([r, g, b]: Rgba): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(a: Rgba, b: Rgba): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

const THEMES = { light: tokens(":root"), dark: { ...tokens(":root"), ...tokens(':root[data-theme="dark"]') } };
const BUTTON_TEXT = "#1b1a17"; // primary buttons keep dark text on hi-vis in both themes

type Pair = [fg: string, bg: string, min: number, note: string];

const TEXT = 4.5;
const MARK = 3;

const PAIRS: Pair[] = [
  ...["ink", "ink-soft", "ink-faint"].flatMap((fg) =>
    ["paper", "paper-raised", "paper-sunk"].map((bg): Pair => [fg, bg, TEXT, "body text"]),
  ),
  ...["asphalt-text", "asphalt-muted"].flatMap((fg) =>
    ["asphalt", "asphalt-raised"].map((bg): Pair => [fg, bg, TEXT, "navigation text"]),
  ),
  ...["signal-high", "signal-medium", "signal-low"].flatMap((fg): Pair[] => [
    [fg, "paper-raised", TEXT, "risk label on a card"],
    [fg, "paper", TEXT, "risk label on the page"],
    [fg, `${fg}-tint|paper-raised`, TEXT, "risk badge"],
  ]),
  ["survey", "paper", TEXT, "link"],
  ["survey", "paper-raised", TEXT, "link on a card"],
  ["survey", "paper-sunk", TEXT, "link on a sunk panel"],
  [BUTTON_TEXT, "hivis", TEXT, "primary button"],
  [BUTTON_TEXT, "hivis-deep", TEXT, "primary button, hover"],
  ["field-line", "paper-raised", MARK, "form field border (WCAG 1.4.11)"],
  ["field-line", "paper", MARK, "form field border on the page"],
  ["field-line", "paper-sunk", MARK, "form field border on a sunk panel"],
  ["survey", "paper", MARK, "focus ring"],
  ["survey", "paper-raised", MARK, "focus ring on a card"],
  ["hivis", "asphalt", MARK, "focus ring on the navigation"],
  ["signal-high", "paper-raised", MARK, "status mark"],
  ["signal-medium", "paper-raised", MARK, "status mark"],
  ["signal-low", "paper-raised", MARK, "status mark"],
];

function colour(theme: Record<string, string>, name: string): Rgba {
  if (name.startsWith("#")) return parse(name);
  const [top, base] = name.split("|");
  const value = parse(theme[top ?? ""] ?? "missing");
  return base ? over(value, colour(theme, base)) : value;
}

describe.each(Object.entries(THEMES))("%s theme contrast", (_theme, theme) => {
  it.each(PAIRS)("%s on %s is at least %s:1 (%s)", (fg, bg, min) => {
    const fgColour = colour(theme, fg);
    const bgColour = colour(theme, bg);
    expect(ratio(fgColour, bgColour)).toBeGreaterThanOrEqual(min);
  });
});

describe("the contrast helpers", () => {
  it("match WCAG's reference values", () => {
    expect(ratio(parse("#000000"), parse("#ffffff"))).toBeCloseTo(21, 5);
    expect(ratio(parse("#767676"), parse("#ffffff"))).toBeCloseTo(4.54, 2);
    expect(over([0, 0, 0, 0.5], [255, 255, 255, 1])).toEqual([127.5, 127.5, 127.5, 1]);
  });
});
