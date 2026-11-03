import type { ReactNode } from "react";

import {
  cannotDraw,
  family,
  fitNumber,
  LINE_HEIGHT,
  measureText,
  measureOf,
  textOf,
} from "./layout";
import type { Ctx } from "./layout";
import { countedText } from "./motion";
import type { TextLayout } from "./spec";

// A part that enters: it fades in and slides up by 3 percent of the height, as far as `p` (the
// eased progress, 0 to 1) has come. It draws nothing before its beat.
export function Enter({ ctx, p, children }: { ctx: Ctx; p: number; children: ReactNode }) {
  if (p <= 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: ctx.width,
        height: ctx.height,
        opacity: p,
        transform: `translateY(${(1 - p) * 0.03 * ctx.height}px)`,
      }}
    >
      {children}
    </div>
  );
}

export type Align = "left" | "center" | "right";

// A text, drawn exactly as the spec laid it out: its font, its size and its lines. Nothing is
// fitted or broken here.
export function Lines({
  layout,
  colour,
  left,
  top,
  width,
  align,
}: {
  layout: TextLayout;
  colour: string;
  left: number;
  top: number;
  width: number;
  align: Align;
}) {
  const lineHeight = layout.size * LINE_HEIGHT;
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width,
        textAlign: align,
        color: colour,
        fontFamily: family(layout.font),
        fontSize: layout.size,
      }}
    >
      {layout.lines.map((line, index) => (
        <div key={index} style={{ height: lineHeight, lineHeight: `${lineHeight}px`, whiteSpace: "nowrap" }}>
          {line}
        </div>
      ))}
    </div>
  );
}

// The text laid out under `path` of the spec.
export function TextAt(props: {
  ctx: Ctx;
  path: string;
  colour: string;
  left: number;
  top: number;
  width: number;
  align: Align;
}) {
  const { ctx, path, ...rest } = props;
  return <Lines layout={textOf(ctx, path)} {...rest} />;
}

// The final width of a number's text at a size.
export function numberWidth(ctx: Ctx, ref: string, size: number): number {
  return measureText(measureOf(ctx, ref).display, "display", size);
}

// A fact or derived value, in the display font, counting up as `p` goes from 0 to 1. `x` is
// where the text starts, ends or is centred, as `anchor` says. The box has the width of the final
// text and the digits grow inside it, so nothing moves while a number counts. The text is the one
// code wrote for the number (G-7), and a year (unit `none`) does not count.
export function Num({
  ctx,
  item,
  size,
  x,
  y,
  anchor,
  p,
  colour,
}: {
  ctx: Ctx;
  item: string;
  size: number;
  x: number;
  y: number;
  anchor: Align;
  p: number;
  colour: string;
}) {
  const measure = measureOf(ctx, item);
  const width = numberWidth(ctx, item, size);
  const left = anchor === "left" ? x : anchor === "center" ? x - width / 2 : x - width;
  const lineHeight = size * LINE_HEIGHT;
  return (
    <div
      style={{
        position: "absolute",
        left,
        top: y,
        width: Math.ceil(width) + 2,
        height: lineHeight,
        lineHeight: `${lineHeight}px`,
        whiteSpace: "nowrap",
        color: colour,
        fontFamily: family("display"),
        fontSize: size,
      }}
    >
      {countedText(measure.display, p, measure.unit !== "none")}
    </div>
  );
}

// A rounded `accent` label with a number in it (the highlight of the bars, the end label of the
// line). Its text is as large as the body text, made smaller when it would not fit.
export function pillSize(ctx: Ctx, ref: string) {
  const display = measureOf(ctx, ref).display;
  const size = fitNumber(display, ctx.bodySize, ctx.W * 0.3);
  const padX = Math.round(0.6 * size);
  const padY = Math.round(0.3 * size);
  const textWidth = numberWidth(ctx, ref, size);
  return {
    size,
    padX,
    padY,
    width: Math.ceil(textWidth) + 2 * padX,
    height: Math.round(size * LINE_HEIGHT) + 2 * padY,
  };
}

export function Pill({
  ctx,
  item,
  right,
  top,
  p,
}: {
  ctx: Ctx;
  item: string;
  right: number;
  top: number;
  p: number;
}) {
  const box = pillSize(ctx, item);
  if (box.width > ctx.W) cannotDraw(`the label for ${item} is wider than the safe area.`);
  const left = right - box.width;
  return (
    <>
      <div
        style={{
          position: "absolute",
          left,
          top,
          width: box.width,
          height: box.height,
          borderRadius: box.height / 2,
          background: ctx.theme.accent,
        }}
      />
      <Num
        ctx={ctx}
        item={item}
        size={box.size}
        x={left + box.padX}
        y={top + box.padY}
        anchor="left"
        p={p}
        colour={ctx.theme.background}
      />
    </>
  );
}
