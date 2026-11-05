import type { Box } from "../types";
import { boxHeight, boxWidth, colourOf, measureOf } from "./ctx";
import type { BCtx } from "./ctx";
import { fitNumberIn, linesHeight, placeText } from "./fit";
import type { TextItem } from "./fit";
import { Item } from "./Item";
import type { ArrowEl, HighlightEl, RingEl } from "./scene";

// The blocks that are shapes: `arrow` and `highlight` (no region: they follow other elements) and
// `progress_ring`.

type Point = { x: number; y: number };

function centre(box: Box): Point {
  return { x: (box.left + box.right) / 2, y: (box.top + box.bottom) / 2 };
}

// Where the line from the centre of `box` towards `target` leaves the box.
function edgePoint(box: Box, target: Point): Point {
  const middle = centre(box);
  const dx = target.x - middle.x;
  const dy = target.y - middle.y;
  const halfWidth = boxWidth(box) / 2;
  const halfHeight = boxHeight(box) / 2;
  const share = Math.min(
    dx === 0 ? Infinity : halfWidth / Math.abs(dx),
    dy === 0 ? Infinity : halfHeight / Math.abs(dy),
  );
  if (!Number.isFinite(share)) return middle;
  return { x: middle.x + dx * share, y: middle.y + dy * share };
}

// --- arrow ---------------------------------------------------------------------------------------

export type ArrowLaid = {
  kind: "arrow";
  id: string;
  // The box that holds the arrow, for an effect that scales it.
  box: Box;
  texts: TextItem[];
  start: Point;
  end: Point;
  colour: string;
  thickness: number;
  head: number;
  issues: string[];
};

// An arrow runs from the edge of one element's region to the edge of the other's, keeping a
// small space at both ends.
export function layoutArrow(ctx: BCtx, element: ArrowEl, from: Box, to: Box): ArrowLaid {
  const fromCentre = centre(from);
  const toCentre = centre(to);
  const start0 = edgePoint(from, toCentre);
  const end0 = edgePoint(to, fromCentre);
  const length0 = Math.hypot(toCentre.x - fromCentre.x, toCentre.y - fromCentre.y);
  const unit =
    length0 === 0
      ? { x: 0, y: 0 }
      : { x: (toCentre.x - fromCentre.x) / length0, y: (toCentre.y - fromCentre.y) / length0 };
  const inset = Math.round(0.01 * ctx.height);
  const start = { x: start0.x + unit.x * inset, y: start0.y + unit.y * inset };
  const end = { x: end0.x - unit.x * inset, y: end0.y - unit.y * inset };
  const along = (end.x - start.x) * unit.x + (end.y - start.y) * unit.y;
  const issues: string[] = [];
  if (along < 0.02 * ctx.height) {
    issues.push(
      `The arrow ${element.id} has no room between its two elements: they touch or overlap.`,
    );
  }
  return {
    kind: "arrow",
    id: element.id,
    box: {
      left: Math.min(start.x, end.x),
      top: Math.min(start.y, end.y),
      right: Math.max(start.x, end.x),
      bottom: Math.max(start.y, end.y),
    },
    texts: [],
    start,
    end,
    colour: colourOf(ctx, element.role ?? "muted"),
    thickness: Math.max(2, Math.round(ctx.height / 270)),
    head: Math.round(0.02 * ctx.height),
    issues,
  };
}

export function DrawArrow({
  ctx,
  l,
  effect,
  p,
}: {
  ctx: BCtx;
  l: ArrowLaid;
  effect: string;
  p: number;
}) {
  if (p <= 0) return null;
  const share = effect === "draw" ? p : 1;
  const tip = {
    x: l.start.x + (l.end.x - l.start.x) * share,
    y: l.start.y + (l.end.y - l.start.y) * share,
  };
  const angle = Math.atan2(l.end.y - l.start.y, l.end.x - l.start.x);
  const spread = Math.PI / 7;
  const wing = (turn: number) => ({
    x: tip.x - l.head * Math.cos(angle + turn),
    y: tip.y - l.head * Math.sin(angle + turn),
  });
  const left = wing(spread);
  const right = wing(-spread);
  return (
    <svg width={ctx.width} height={ctx.height} style={{ position: "absolute", left: 0, top: 0 }}>
      <polyline
        points={`${l.start.x},${l.start.y} ${tip.x},${tip.y}`}
        fill="none"
        stroke={l.colour}
        strokeWidth={l.thickness}
        strokeLinecap="round"
      />
      <polyline
        points={`${left.x},${left.y} ${tip.x},${tip.y} ${right.x},${right.y}`}
        fill="none"
        stroke={l.colour}
        strokeWidth={l.thickness}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// --- highlight -----------------------------------------------------------------------------------

export type HighlightLaid = {
  kind: "highlight";
  id: string;
  box: Box;
  texts: TextItem[];
  colour: string;
  stroke: number;
  radius: number;
};

// A box drawn around another element's region, as far out as the gutter that the region keeps
// free, so its line never reaches the next region or the caption area below the grid.
export function layoutHighlight(ctx: BCtx, element: HighlightEl, target: Box): HighlightLaid {
  const stroke = Math.max(3, Math.round(ctx.height / 360));
  const pad = Math.max(0, Math.round(0.005 * ctx.height) - Math.ceil(stroke / 2));
  return {
    kind: "highlight",
    id: element.id,
    box: {
      left: target.left - pad,
      top: target.top - pad,
      right: target.right + pad,
      bottom: target.bottom + pad,
    },
    texts: [],
    colour: colourOf(ctx, element.role ?? "accent"),
    stroke,
    radius: Math.round(0.01 * ctx.height),
  };
}

export function DrawHighlight({
  ctx,
  l,
  effect,
  p,
}: {
  ctx: BCtx;
  l: HighlightLaid;
  effect: string;
  p: number;
}) {
  if (p <= 0) return null;
  const width = boxWidth(l.box);
  const height = boxHeight(l.box);
  const perimeter = 2 * (width + height);
  const share = effect === "draw" ? p : 1;
  return (
    <svg width={ctx.width} height={ctx.height} style={{ position: "absolute", left: 0, top: 0 }}>
      <rect
        x={l.box.left}
        y={l.box.top}
        width={width}
        height={height}
        rx={l.radius}
        fill="none"
        stroke={l.colour}
        strokeWidth={l.stroke}
        strokeDasharray={perimeter}
        strokeDashoffset={perimeter * (1 - share)}
      />
    </svg>
  );
}

// --- progress_ring -------------------------------------------------------------------------------

export type RingLaid = {
  kind: "progress_ring";
  id: string;
  box: Box;
  texts: TextItem[];
  centre: Point;
  radius: number;
  thickness: number;
  // The share of the ring the value fills, from 0 to 1.
  share: number;
  colour: string;
};

// A ring in the middle of its region, as large as the region's shorter side, filled as far as the
// value (a percent), with the value in the middle.
export function layoutRing(ctx: BCtx, element: RingEl, box: Box): RingLaid {
  const measure = measureOf(ctx, element.value);
  const diameter = Math.min(boxWidth(box), boxHeight(box));
  const thickness = Math.max(2, Math.round(0.12 * diameter));
  const middle = centre(box);
  const inner = diameter - 2 * thickness;
  const size = fitNumberIn(measure.display, Math.round(0.3 * diameter), 0.9 * inner, inner);
  const item: TextItem = {
    part: "value",
    group: 0,
    text: measure.display,
    font: "display",
    size,
    lines: [measure.display],
    box: placeText(
      [measure.display],
      "display",
      size,
      "center",
      { left: middle.x - inner / 2, right: middle.x + inner / 2 },
      middle.y - linesHeight(1, size) / 2,
    ),
    align: "center",
    colour: ctx.theme.text,
    counts: measure.unit !== "none",
  };
  return {
    kind: "progress_ring",
    id: element.id,
    box,
    texts: [item],
    centre: middle,
    radius: (diameter - thickness) / 2,
    thickness,
    share: Math.min(100, Math.max(0, measure.value)) / 100,
    colour: colourOf(ctx, element.role ?? "accent"),
  };
}

export function DrawRing({
  ctx,
  l,
  effect,
  p,
}: {
  ctx: BCtx;
  l: RingLaid;
  effect: string;
  p: number;
}) {
  const fills = effect === "grow" || effect === "draw" || effect === "count_up";
  const progress = fills ? p : 1;
  const circumference = 2 * Math.PI * l.radius;
  const item = l.texts[0];
  return (
    <>
      <svg width={ctx.width} height={ctx.height} style={{ position: "absolute", left: 0, top: 0 }}>
        <circle
          cx={l.centre.x}
          cy={l.centre.y}
          r={l.radius}
          fill="none"
          stroke={ctx.theme.surface}
          strokeWidth={l.thickness}
        />
        <circle
          cx={l.centre.x}
          cy={l.centre.y}
          r={l.radius}
          fill="none"
          stroke={l.colour}
          strokeWidth={l.thickness}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - l.share * progress)}
          transform={`rotate(-90 ${l.centre.x} ${l.centre.y})`}
        />
      </svg>
      {item !== undefined && <Item item={item} count={effect === "count_up" ? p : 1} />}
    </>
  );
}
