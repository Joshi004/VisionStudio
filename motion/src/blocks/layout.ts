// The layout of a scene (§4.5.2): where every element sits and every text with its font, size,
// lines and box. The `Blocks` composition draws from it, and `POST /layout` reports from it, so
// what the model is told is what is drawn.
import type { GraphicInput } from "../types";
import { cannotDraw, GRID, makeBCtx, regionBox } from "./ctx";
import type { BCtx, CtxOptions } from "./ctx";
import type { Box } from "../types";
import type { Element, Region, Scene } from "./scene";
import { layoutBars, layoutLine } from "./Series";
import type { BarsLaid, LineLaid } from "./Series";
import { layoutPanel } from "./Panel";
import type { PanelLaid } from "./Panel";
import { layoutArrow, layoutHighlight, layoutRing } from "./Shapes";
import type { ArrowLaid, HighlightLaid, RingLaid } from "./Shapes";
import { layoutTable } from "./Table";
import type { TableLaid } from "./Table";
import { layoutBadge, layoutCounter, layoutNode, layoutText } from "./TextBlocks";
import type { BadgeLaid, CounterLaid, NodeLaid, TextLaid } from "./TextBlocks";

export type Laid =
  | TextLaid
  | CounterLaid
  | BarsLaid
  | LineLaid
  | NodeLaid
  | ArrowLaid
  | TableLaid
  | BadgeLaid
  | HighlightLaid
  | RingLaid
  | PanelLaid;

export type Issue = { element: string; message: string };

export type SceneLayout = {
  ctx: BCtx;
  // One entry for each element of the scene, in the same order.
  laid: Laid[];
  issues: Issue[];
};

function checkRegion(element: Element, region: Region): void {
  const [firstColumn, firstRow, lastColumn, lastRow] = region;
  const inside = (value: number) => Number.isInteger(value) && value >= 1 && value <= GRID;
  if (
    ![firstColumn, firstRow, lastColumn, lastRow].every(inside) ||
    firstColumn > lastColumn ||
    firstRow > lastRow
  ) {
    cannotDraw(`the region of ${element.id} is not inside the ${GRID} x ${GRID} grid.`);
  }
}

// `options` is for a callout (CMO-004); a shot graphic passes none.
export function layoutScene(input: GraphicInput, scene: Scene, options?: CtxOptions): SceneLayout {
  const ctx = makeBCtx(input, options);
  // The boxes of the elements that have a region, which the arrows and highlights follow.
  const boxes = new Map<string, Box>();
  for (const element of scene.elements) {
    if ("region" in element) {
      checkRegion(element, element.region);
      boxes.set(element.id, regionBox(ctx, element.region));
    }
  }
  const boxOf = (id: string, by: string): Box => {
    const found = boxes.get(id);
    if (found === undefined) cannotDraw(`${by} points at ${id}, which has no region.`);
    return found;
  };

  const laid: Laid[] = scene.elements.map((element): Laid => {
    switch (element.block) {
      case "text":
        return layoutText(ctx, element, boxOf(element.id, element.id));
      case "counter":
        return layoutCounter(ctx, element, boxOf(element.id, element.id));
      case "bar_series":
        return layoutBars(ctx, element, boxOf(element.id, element.id));
      case "line_series":
        return layoutLine(ctx, element, boxOf(element.id, element.id));
      case "node":
        return layoutNode(ctx, element, boxOf(element.id, element.id));
      case "table":
        return layoutTable(ctx, element, boxOf(element.id, element.id));
      case "panel":
        return layoutPanel(ctx, element, boxOf(element.id, element.id));
      case "badge":
        return layoutBadge(ctx, element, boxOf(element.id, element.id));
      case "progress_ring":
        return layoutRing(ctx, element, boxOf(element.id, element.id));
      case "arrow":
        return layoutArrow(ctx, element, boxOf(element.from, element.id), boxOf(element.to, element.id));
      case "highlight":
        return layoutHighlight(ctx, element, boxOf(element.target, element.id));
    }
  });

  const issues: Issue[] = [];
  for (const entry of laid) {
    if ("issues" in entry) {
      for (const message of entry.issues) issues.push({ element: entry.id, message });
    }
  }
  return { ctx, laid, issues };
}
