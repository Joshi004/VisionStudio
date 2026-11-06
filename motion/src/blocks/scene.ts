// The block scene that GFX-009 stores (§4.5.2 of Graphics_lab_implementation_phases.md) and the
// light check the composition makes before it draws it. The backend has already checked the scene
// in depth (`graphics_blocks.check_scene`); this file only makes sure the scene is the library's
// version and has the parts the drawing code reads, so a wrong input fails with a clear message.
//
// The motion server imports this file with its `.ts` extension (Node's type stripping), so it has
// no imports and only uses syntax that can be erased.

// The version of the block library this renderer draws. /health reports it, and a scene written for
// another version is refused. The same number is `graphics_blocks.BLOCKS_VERSION`.
export const BLOCKS_VERSION = 1;

export type ColourRole = "text" | "muted" | "accent" | "positive" | "negative" | "number";
export type Align = "left" | "center" | "right";
export type Region = [number, number, number, number];

// `beat` for a block that enters once, `beats` (one for each part) for a series.
export type Enter = { beat?: string; beats?: string[]; effect: string };
export type Exit = { beat: string; effect: string };

type Common = { id: string; enter: Enter; exit?: Exit };
type Placed = Common & { region: Region };

export type TextEl = Placed & {
  block: "text";
  style: "title" | "label" | "body";
  text: string;
  align?: Align;
  role?: ColourRole;
  // Callout only: the part's colour, set from the part by `readCalloutScene` (callout.ts).
  colour?: string;
};
export type CounterEl = Placed & {
  block: "counter";
  value: string;
  label?: string;
  align?: Align;
  role?: ColourRole;
};
export type BarSeriesEl = Placed & {
  block: "bar_series";
  values: string[];
  labels: string[];
  orientation: "vertical" | "horizontal";
  emphasis?: string[];
};
export type LineSeriesEl = Placed & {
  block: "line_series";
  values: string[];
  labels: string[];
  area?: boolean;
};
export type NodeEl = Placed & { block: "node"; label: string; role?: ColourRole; colour?: string };
export type ArrowEl = Common & { block: "arrow"; from: string; to: string; role?: ColourRole };
export type TableCell = string | { value: string };
export type TableEl = Placed & { block: "table"; header?: string[]; rows: TableCell[][] };
export type BadgeEl = Placed & {
  block: "badge";
  value?: string;
  text?: string;
  role?: ColourRole;
  colour?: string;
};
// Callout only (CMO-004): a box in `surface` under the other elements. A shot graphic's scene never
// has one: `BLOCKS` below, which `readScene` checks, does not list it.
export type PanelEl = Placed & { block: "panel" };
export type HighlightEl = Common & { block: "highlight"; target: string; role?: ColourRole };
export type RingEl = Placed & { block: "progress_ring"; value: string; role?: ColourRole };

export type Element =
  | TextEl
  | CounterEl
  | BarSeriesEl
  | LineSeriesEl
  | NodeEl
  | ArrowEl
  | TableEl
  | BadgeEl
  | HighlightEl
  | RingEl
  | PanelEl;

export type Scene = { blocks_version: number; elements: Element[] };

const BLOCKS = [
  "text",
  "counter",
  "bar_series",
  "line_series",
  "node",
  "arrow",
  "table",
  "badge",
  "highlight",
  "progress_ring",
];

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// The scene a render's `input` holds, or an Error that says what is wrong with it.
export function readScene(input: unknown): Scene {
  if (!isObject(input)) throw new Error("The block scene is missing from the render's input.");
  if (input["blocks_version"] !== BLOCKS_VERSION) {
    throw new Error(
      `The scene was written for block library version ${String(input["blocks_version"])}; ` +
        `this renderer draws version ${BLOCKS_VERSION}.`,
    );
  }
  const elements = input["elements"];
  if (!Array.isArray(elements) || elements.length === 0) {
    throw new Error("The block scene has no elements.");
  }
  for (const element of elements) {
    if (!isObject(element) || typeof element["id"] !== "string") {
      throw new Error("An element of the block scene has no id.");
    }
    if (typeof element["block"] !== "string" || !BLOCKS.includes(element["block"])) {
      throw new Error(`The block ${JSON.stringify(element["block"])} is not in the library.`);
    }
    if (!isObject(element["enter"]) || typeof element["enter"]["effect"] !== "string") {
      throw new Error(`The element ${element["id"]} has no entrance.`);
    }
  }
  return input as unknown as Scene;
}
