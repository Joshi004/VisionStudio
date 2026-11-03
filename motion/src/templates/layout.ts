// The geometry the five templates share (§4.5.1, "The template layout"). GFX-008 draws the same
// layout in Python from the same numbers.
import { DISPLAY_FONT, TEXT_FONT } from "../fonts";
import type { GraphicInput, Measure, Resolved, Theme } from "../types";
import { progressAt } from "./motion";
import type { Role, TemplateSpec, TextLayout } from "./spec";

// A line of text is this many times its size high; a text may fill this much of its space.
export const LINE_HEIGHT = 1.2;
export const FIT_SHARE = 0.97;

export type Ctx = {
  frame: number;
  width: number;
  height: number;
  resolved: Resolved;
  theme: Theme;
  spec: TemplateSpec;
  motion: string;
  // The safe area, and its width.
  left: number;
  top: number;
  right: number;
  W: number;
  // The title size and the body size of the look rules, before any text is made smaller.
  titleSize: number;
  bodySize: number;
  // The lowest y a part may reach: the top of the caption area, less 3 percent of the height.
  bottom: number;
  // The width of the thin lines (grid, baseline, node borders).
  stroke: number;
  landscape: boolean;
};

export function makeCtx(frame: number, input: GraphicInput, spec: TemplateSpec): Ctx {
  const { width, height, resolved } = input;
  const landscape = width >= height;
  const area = resolved.safe_area;
  return {
    frame,
    width,
    height,
    resolved,
    theme: resolved.theme,
    spec,
    motion: resolved.theme.motion,
    left: area.left,
    top: area.top,
    right: area.right,
    W: area.right - area.left,
    titleSize: Math.round((landscape ? 0.06 : 0.036) * height),
    bodySize: Math.round((landscape ? 0.032 : 0.024) * height),
    bottom: resolved.caption_zone.top - Math.round(0.03 * height),
    stroke: Math.max(1, Math.round(height / 540)),
    landscape,
  };
}

// A template that cannot be drawn: the render fails, and the card shows this message.
export function cannotDraw(message: string): never {
  throw new Error(`The template cannot be drawn: ${message}`);
}

export function family(role: Role): string {
  return role === "display" ? DISPLAY_FONT : TEXT_FONT;
}

// --- What the resolved brief holds ---------------------------------------------------------------

export function beatFrame(ctx: Ctx, beat: string): number {
  const found = ctx.resolved.beats[beat];
  if (found === undefined) cannotDraw(`the beat ${beat} is not in the resolved brief.`);
  return found.frame;
}

// How far the part that enters on `beat` has come, from 0 to 1.
export function enterOf(ctx: Ctx, beat: string): number {
  return progressAt(ctx.frame, beatFrame(ctx, beat), ctx.motion);
}

export function measureOf(ctx: Ctx, ref: string): Measure {
  const found = ctx.resolved.facts[ref] ?? ctx.resolved.derived[ref];
  if (found === undefined) cannotDraw(`${ref} is not a fact or a derived value.`);
  return found;
}

export function textOf(ctx: Ctx, path: string): TextLayout {
  const found = ctx.spec.text[path];
  if (found === undefined) cannotDraw(`the spec has no layout for the text "${path}".`);
  return found;
}

// --- Sizes ---------------------------------------------------------------------------------------

export function linesHeight(layout: TextLayout): number {
  return layout.lines.length * layout.size * LINE_HEIGHT;
}

export function textHeight(size: number, lines = 1): number {
  return lines * size * LINE_HEIGHT;
}

// The top of the content box: below the title when there is one.
export function contentTop(ctx: Ctx): number {
  const title = ctx.spec.text["title"];
  if (title === undefined) return ctx.top;
  return ctx.top + Math.round(linesHeight(title)) + Math.round(0.04 * ctx.height);
}

// --- Measuring numbers ---------------------------------------------------------------------------

// The width of a text in a font at one size. The browser measures it in the font's own file, once
// at a large size and scaled, so the answer does not depend on the size asked for.
const REFERENCE = 1000;
const widths = new Map<string, number>();
let canvas: CanvasRenderingContext2D | null = null;

export function measureText(text: string, role: Role, size: number): number {
  const key = `${role}|${text}`;
  let unit = widths.get(key);
  if (unit === undefined) {
    canvas ??= document.createElement("canvas").getContext("2d");
    if (canvas === null) cannotDraw("the browser cannot measure text.");
    canvas.font = `${REFERENCE}px "${family(role)}"`;
    unit = canvas.measureText(text).width / REFERENCE;
    widths.set(key, unit);
  }
  return unit * size;
}

// The size a number is drawn at: `base`, or the largest whole pixel size at which its final text
// is within 97 percent of its space. The text of a number is written by code and is not split.
export function fitNumber(text: string, base: number, space: number): number {
  const width = measureText(text, "display", base);
  const limit = space * FIT_SHARE;
  return width <= limit ? base : Math.max(1, Math.floor((base * limit) / width));
}

// --- Colours -------------------------------------------------------------------------------------

// `#RRGGBB` with an opacity from 0 to 1.
export function withAlpha(hex: string, alpha: number): string {
  const red = parseInt(hex.slice(1, 3), 16);
  const green = parseInt(hex.slice(3, 5), 16);
  const blue = parseInt(hex.slice(5, 7), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

// The colour of a change: `positive` above zero, `negative` below, `text` at zero.
export function changeColour(ctx: Ctx, value: number): string {
  if (value > 0) return ctx.theme.positive;
  if (value < 0) return ctx.theme.negative;
  return ctx.theme.text;
}
