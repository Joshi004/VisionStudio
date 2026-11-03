// What every block reads of the video: its size, the colours, the safe area, and the 12 x 12 grid
// inside it (§4.5.2). Nothing here depends on the frame, so the layout of a scene is the same on
// every frame, and the report of `POST /layout` is the layout that gets drawn.
import type { Box, GraphicInput, Measure, Resolved, Theme } from "../types";
import type { ColourRole, Region } from "./scene";

export const GRID = 12;

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
};

// A scene that cannot be drawn: the render fails, and the card shows this message.
export function cannotDraw(message: string): never {
  throw new Error(`The block scene cannot be drawn: ${message}`);
}

export function makeBCtx(input: GraphicInput): BCtx {
  const { width, height, resolved } = input;
  const landscape = width >= height;
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
    titleSize: Math.round((landscape ? 0.06 : 0.036) * height),
    bodySize: Math.round((landscape ? 0.032 : 0.024) * height),
    stroke: Math.max(1, Math.round(height / 540)),
    gutter: Math.round(0.005 * height),
    cellW: safeWidth / GRID,
    cellH: (area.bottom - area.top) / GRID,
    landscape,
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
