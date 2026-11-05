import { measureText } from "../templates/layout";
import type { Box } from "../types";
import { boxHeight, boxWidth, colourOf, measureOf } from "./ctx";
import type { BCtx } from "./ctx";
import { fitNumberIn, fitText, linesHeight, placeText } from "./fit";
import type { TextItem } from "./fit";
import { Item } from "./Item";
import type { BadgeEl, CounterEl, NodeEl, TextEl } from "./scene";

// The four blocks that are one text, or one text in a shape: `text`, `counter`, `badge`, `node`.
// Each has a `layout` (pure: the texts and the shapes with their boxes) and a component that draws
// that layout from the progress of its entrance.

export type TextLaid = { kind: "text"; id: string; box: Box; texts: TextItem[] };

export function layoutText(ctx: BCtx, element: TextEl, box: Box): TextLaid {
  const title = element.style === "title";
  const font = title ? "display" : "text";
  const maxLines = element.style === "body" ? 3 : 2;
  const fitted = fitText(
    element.text,
    font,
    title ? ctx.titleSize : ctx.bodySize,
    boxWidth(box),
    boxHeight(box),
    maxLines,
  );
  const align = element.align ?? "left";
  const role = element.role ?? (element.style === "label" ? "muted" : "text");
  const item: TextItem = {
    part: "text",
    group: 0,
    text: element.text,
    font,
    size: fitted.size,
    lines: fitted.lines,
    box: placeText(fitted.lines, font, fitted.size, align, box, box.top),
    align,
    colour: colourOf(ctx, role),
    counts: false,
  };
  return { kind: "text", id: element.id, box, texts: [item] };
}

export function DrawText({ l, effect, p }: { l: TextLaid; effect: string; p: number }) {
  const item = l.texts[0];
  if (item === undefined) return null;
  return <Item item={item} typedShare={effect === "typewriter" ? p : 1} />;
}

// --- counter -------------------------------------------------------------------------------------

export type CounterLaid = { kind: "counter"; id: string; box: Box; texts: TextItem[] };

export function layoutCounter(ctx: BCtx, element: CounterEl, box: Box): CounterLaid {
  const measure = measureOf(ctx, element.value);
  const align = element.align ?? "center";
  const colour = colourOf(ctx, element.role ?? "text");
  const gap = Math.round(0.01 * ctx.height);
  const label =
    element.label === undefined
      ? null
      : fitText(element.label, "text", ctx.bodySize, boxWidth(box), 0.3 * boxHeight(box), 2);
  const labelHeight = label === null ? 0 : Math.round(linesHeight(label.lines.length, label.size));
  const valueSpace = boxHeight(box) - (label === null ? 0 : labelHeight + gap);
  const base = Math.round((ctx.landscape ? 0.14 : 0.07) * ctx.height);
  const size = fitNumberIn(measure.display, base, boxWidth(box), valueSpace);
  const stack = Math.round(linesHeight(1, size)) + (label === null ? 0 : gap + labelHeight);
  const top = box.top + (boxHeight(box) - stack) / 2;
  const texts: TextItem[] = [
    {
      part: "value",
      group: 0,
      text: measure.display,
      font: "display",
      size,
      lines: [measure.display],
      box: placeText([measure.display], "display", size, align, box, top),
      align,
      colour,
      counts: measure.unit !== "none",
    },
  ];
  if (label !== null && element.label !== undefined) {
    texts.push({
      part: "label",
      group: 0,
      text: element.label,
      font: "text",
      size: label.size,
      lines: label.lines,
      box: placeText(
        label.lines,
        "text",
        label.size,
        align,
        box,
        top + Math.round(linesHeight(1, size)) + gap,
      ),
      align,
      colour: ctx.theme.muted,
      counts: false,
    });
  }
  return { kind: "counter", id: element.id, box, texts };
}

export function DrawCounter({ l, effect, p }: { l: CounterLaid; effect: string; p: number }) {
  return (
    <>
      {l.texts.map((item) => (
        <Item key={item.part} item={item} count={effect === "count_up" ? p : 1} />
      ))}
    </>
  );
}

// --- badge ---------------------------------------------------------------------------------------

export type BadgeLaid = {
  kind: "badge";
  id: string;
  box: Box;
  texts: TextItem[];
  pill: Box;
  fill: string;
};

// A rounded label that has the size of its text and sits in the middle of its region. The text is
// as large as a title, made smaller when the label would not fit the region.
export function layoutBadge(ctx: BCtx, element: BadgeEl, box: Box): BadgeLaid {
  const measure = element.value === undefined ? null : measureOf(ctx, element.value);
  const text = measure === null ? (element.text ?? "") : measure.display;
  const font = measure === null ? "text" : "display";
  const unit = measureText(text, font, 1);
  const size = Math.max(
    1,
    Math.min(
      ctx.titleSize,
      unit > 0 ? Math.floor((0.97 * boxWidth(box)) / (unit + 1.2)) : ctx.titleSize,
      Math.floor(boxHeight(box) / 1.8),
    ),
  );
  const padX = Math.round(0.6 * size);
  const padY = Math.round(0.3 * size);
  const textWidth = Math.ceil(measureText(text, font, size));
  const pillWidth = textWidth + 2 * padX;
  const pillHeight = Math.round(size * 1.2) + 2 * padY;
  const left = Math.round((box.left + box.right - pillWidth) / 2);
  const top = Math.round((box.top + box.bottom - pillHeight) / 2);
  const item: TextItem = {
    part: "text",
    group: 0,
    text,
    font,
    size,
    lines: [text],
    box: placeText([text], font, size, "left", { left: left + padX, right: left + pillWidth }, top + padY),
    align: "left",
    colour: ctx.theme.background,
    counts: measure !== null && measure.unit !== "none",
  };
  return {
    kind: "badge",
    id: element.id,
    box,
    texts: [item],
    pill: { left, top, right: left + pillWidth, bottom: top + pillHeight },
    fill: colourOf(ctx, element.role ?? "accent"),
  };
}

export function DrawBadge({ l, effect, p }: { l: BadgeLaid; effect: string; p: number }) {
  const item = l.texts[0];
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: l.pill.left,
          top: l.pill.top,
          width: boxWidth(l.pill),
          height: boxHeight(l.pill),
          borderRadius: boxHeight(l.pill) / 2,
          background: l.fill,
        }}
      />
      {item !== undefined && <Item item={item} count={effect === "count_up" ? p : 1} />}
    </>
  );
}

// --- node ----------------------------------------------------------------------------------------

export type NodeLaid = {
  kind: "node";
  id: string;
  box: Box;
  texts: TextItem[];
  border: string;
  radius: number;
  stroke: number;
};

// A rounded box in `surface` with a border, its label in the middle.
export function layoutNode(ctx: BCtx, element: NodeEl, box: Box): NodeLaid {
  const inset = Math.round(0.02 * ctx.height);
  const fitted = fitText(
    element.label,
    "text",
    ctx.bodySize,
    boxWidth(box) - 2 * inset,
    boxHeight(box) - 2 * inset,
    2,
  );
  const top = box.top + (boxHeight(box) - linesHeight(fitted.lines.length, fitted.size)) / 2;
  const item: TextItem = {
    part: "label",
    group: 0,
    text: element.label,
    font: "text",
    size: fitted.size,
    lines: fitted.lines,
    box: placeText(fitted.lines, "text", fitted.size, "center", box, top),
    align: "center",
    colour: ctx.theme.text,
    counts: false,
  };
  return {
    kind: "node",
    id: element.id,
    box,
    texts: [item],
    border: colourOf(ctx, element.role ?? "accent"),
    radius: Math.min(Math.round(0.3 * fitted.size), Math.floor(Math.min(boxWidth(box), boxHeight(box)) / 2)),
    stroke: Math.max(2, Math.round(ctx.height / 360)),
  };
}

export function DrawNode({ ctx, l }: { ctx: BCtx; l: NodeLaid }) {
  const item = l.texts[0];
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: l.box.left,
          top: l.box.top,
          width: boxWidth(l.box),
          height: boxHeight(l.box),
          boxSizing: "border-box",
          background: ctx.theme.surface,
          border: `${l.stroke}px solid ${l.border}`,
          borderRadius: l.radius,
        }}
      />
      {item !== undefined && <Item item={item} />}
    </>
  );
}
