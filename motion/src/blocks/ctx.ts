// What every block reads of the video: its size, the colours, the safe area, and the 12 x 12 grid
// inside it (§4.5.2). Nothing here depends on the frame, so the layout of a scene is the same on
// every frame, and the report of `POST /layout` is the layout that gets drawn.
import type { Box, GraphicInput, Measure, Resolved, Theme } from "../types";
import type { ColourRole, Region } from "./scene";

export const GRID = 12;

// What a callout changes in how the blocks are laid out (CMO-004). The shot graphics pass nothing,
// so they are laid out exactly as before. The text sizes read the output frame (not the zone the
// callout is drawn in), the corners and the panel come from the callout look.
export type CtxOptions = {
  frameWidth: number;
  frameHeight: number;
  corners: string;
  panelOpacity: number;
};

export type BCtx = {
  width: number;
  height: number;
  resolved: Resolved;
  theme: Theme;
  motion: string;
  // The safe area, and its width.
  left: number;
  top: number;
  right: number;
  W: number;
  // The title size and the body size of the look rules (§4.5.1).
  titleSize: number;
  bodySize: number;
  // The width of the thin lines.
  stroke: number;
  // The space kept on each side of a region.
  gutter: number;
  cellW: number;
  cellH: number;
  landscape: boolean;
  // The height the text sizes read: the frame's for a callout, else the canvas's.
  textHeight: number;
  // Callout only: the corners of a panel and a node (`sharp`, `soft` or `round`), and how opaque a
  // panel is. Null for a shot graphic.
  corners: string | null;
  panelOpacity: number;
};

// The radius a callout look's `corners` gives a box, or null when the scene has no look (a shot
// graphic, which draws its own radius).
export function cornerRadius(ctx: BCtx, box: Box): number | null {
  if (ctx.corners === null) return null;
  if (ctx.corners === "sharp") return 0;
  if (ctx.corners === "round") return Math.floor(Math.min(boxWidth(box), boxHeight(box)) / 2);
  return Math.round(0.012 * ctx.textHeight);
}

// A scene that cannot be drawn: the render fails, and the card shows this message.
export function cannotDraw(message: string): never {
  throw new Error(`The block scene cannot be drawn: ${message}`);
}

export function makeBCtx(input: GraphicInput, options?: CtxOptions): BCtx {
  const { width, height, resolved } = input;
  const textHeight = options === undefined ? height : options.frameHeight;
  const landscape = options === undefined ? width >= height : options.frameWidth >= options.frameHeight;
  const area = resolved.safe_area;
  const safeWidth = area.right - area.left;
  return {
    width,
    height,
    resolved,
    theme: resolved.theme,
    motion: resolved.theme.motion,
    left: area.left,
    top: area.top,
    right: area.right,
    W: safeWidth,
    titleSize: Math.round((landscape ? 0.06 : 0.036) * textHeight),
    bodySize: Math.round((landscape ? 0.032 : 0.024) * textHeight),
    stroke: Math.max(1, Math.round(height / 540)),
    gutter: Math.round(0.005 * height),
    cellW: safeWidth / GRID,
    cellH: (area.bottom - area.top) / GRID,
    landscape,
    textHeight,
    corners: options === undefined ? null : options.corners,
    panelOpacity: options === undefined ? 1 : options.panelOpacity,
  };
}

// A region of the grid as pixels, less the gutter on each side. Columns and rows count from 1.
export function regionBox(ctx: BCtx, region: Region): Box {
  const [firstColumn, firstRow, lastColumn, lastRow] = region;
  return {
    left: Math.round(ctx.left + (firstColumn - 1) * ctx.cellW + ctx.gutter),
    top: Math.round(ctx.top + (firstRow - 1) * ctx.cellH + ctx.gutter),
    right: Math.round(ctx.left + lastColumn * ctx.cellW - ctx.gutter),
    bottom: Math.round(ctx.top + lastRow * ctx.cellH - ctx.gutter),
  };
}

export function measureOf(ctx: BCtx, ref: string): Measure {
  const found = ctx.resolved.facts[ref] ?? ctx.resolved.derived[ref];
  if (found === undefined) cannotDraw(`${ref} is not a fact or a derived value.`);
  return found;
}

export function beatFrame(ctx: BCtx, beat: string): number {
  const found = ctx.resolved.beats[beat];
  if (found === undefined) cannotDraw(`the beat ${beat} is not in the resolved brief.`);
  return found.frame;
}

export function colourOf(ctx: BCtx, role: ColourRole): string {
  return ctx.theme[role];
}

export function boxWidth(box: Box): number {
  return box.right - box.left;
}

export function boxHeight(box: Box): number {
  return box.bottom - box.top;
}
