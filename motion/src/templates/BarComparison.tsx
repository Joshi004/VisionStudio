import {
  cannotDraw,
  contentTop,
  enterOf,
  fitNumber,
  linesHeight,
  measureOf,
  textHeight,
  textOf,
} from "./layout";
import type { Ctx } from "./layout";
import type { BarSpec } from "./spec";
import { Enter, Num, numberWidth, Pill, pillSize, TextAt } from "./Text";

// The most a bar is thick: 20 percent of the safe width (vertical) or 9 percent of the height
// (horizontal), so two bars are not two slabs.
const MAX_VERTICAL_THICKNESS = 0.2;
const MAX_HORIZONTAL_THICKNESS = 0.09;

// Two to six values side by side (§4.5.1). Bars start at zero, every bar has the same unit, and a
// bar grows over the same time as other parts arrive. A bar with `emphasis` is `accent`; when some
// bars have it, the others are `muted`; when none has it, all are `accent`.
export function BarComparison({ ctx, spec }: { ctx: Ctx; spec: BarSpec }) {
  const { fields, beats } = spec;
  const bars = fields.bars.map((bar, index) => {
    const beat = beats.bars[index];
    if (beat === undefined) cannotDraw(`bar ${index + 1} has no beat.`);
    const measure = measureOf(ctx, bar.value);
    return {
      value: measure.value,
      display: measure.display,
      ref: bar.value,
      p: enterOf(ctx, beat),
      label: `bars.${index}.label`,
      emphasis: bar.emphasis === true,
    };
  });
  const anyEmphasis = bars.some((bar) => bar.emphasis);
  const colourOf = (emphasis: boolean) =>
    !anyEmphasis || emphasis ? ctx.theme.accent : ctx.theme.muted;

  const highlight = fields.highlight;
  const pill = highlight === undefined ? null : pillSize(ctx, highlight.value);
  const gap = Math.round(0.01 * ctx.height);
  const lowest = Math.min(0, ...bars.map((bar) => bar.value));
  const highest = Math.max(0, ...bars.map((bar) => bar.value));
  const range = highest - lowest || 1;
  const top = contentTop(ctx) + (pill === null ? 0 : pill.height + Math.round(0.02 * ctx.height));
  const radius = Math.max(2, Math.round(ctx.height / 270));

  const highlightPart =
    highlight === undefined ? null : (
      <Enter ctx={ctx} p={enterOf(ctx, highlight.beat)}>
        <Pill
          ctx={ctx}
          item={highlight.value}
          right={ctx.right}
          top={contentTop(ctx)}
          p={enterOf(ctx, highlight.beat)}
        />
      </Enter>
    );

  if (spec.variant === "vertical") {
    const slot = ctx.W / bars.length;
    const barWidth = Math.round(Math.min(0.6 * slot, MAX_VERTICAL_THICKNESS * ctx.W));
    const valueSize = Math.min(
      ...bars.map((bar) => fitNumber(bar.display, ctx.bodySize, slot)),
    );
    const valueRow = Math.round(textHeight(valueSize)) + gap;
    const labelsHeight =
      Math.round(Math.max(...bars.map((bar) => linesHeight(textOf(ctx, bar.label))))) + gap;
    const labelTop = ctx.bottom - labelsHeight + gap;
    const plotTop = top + valueRow;
    const plotBottom = labelTop - gap - (lowest < 0 ? valueRow : 0);
    if (plotBottom - plotTop < Math.round(0.15 * ctx.height)) {
      cannotDraw("the bars, their values and their labels do not fit above the caption area.");
    }
    const scale = (plotBottom - plotTop) / range;
    const baseline = Math.round(plotTop + highest * scale);
    const first = bars[0]?.p ?? 0;

    return (
      <>
        {highlightPart}
        {first > 0 && (
          <div
            style={{
              position: "absolute",
              left: ctx.left,
              top: baseline - Math.floor(ctx.stroke / 2),
              width: ctx.W,
              height: ctx.stroke,
              background: ctx.theme.muted,
              opacity: first,
            }}
          />
        )}
        {bars.map((bar, index) => {
          const centre = ctx.left + (index + 0.5) * slot;
          const full = Math.abs(bar.value) * scale;
          const grown = Math.round(full * bar.p);
          const barTop = bar.value >= 0 ? baseline - grown : baseline;
          const finalTop = bar.value >= 0 ? baseline - Math.round(full) : baseline;
          const valueY =
            bar.value >= 0
              ? finalTop - gap - Math.round(textHeight(valueSize))
              : baseline + Math.round(full) + gap;
          return (
            <div key={index}>
              <div
                style={{
                  position: "absolute",
                  left: Math.round(centre - barWidth / 2),
                  top: barTop,
                  width: barWidth,
                  height: grown,
                  background: colourOf(bar.emphasis),
                  borderRadius: radius,
                }}
              />
              <Enter ctx={ctx} p={bar.p}>
                <Num
                  ctx={ctx}
                  item={bar.ref}
                  size={valueSize}
                  x={centre}
                  y={valueY}
                  anchor="center"
                  p={bar.p}
                  colour={ctx.theme.text}
                />
                <TextAt
                  ctx={ctx}
                  path={bar.label}
                  colour={ctx.theme.muted}
                  left={ctx.left + index * slot}
                  top={labelTop}
                  width={slot}
                  align="center"
                />
              </Enter>
            </div>
          );
        })}
      </>
    );
  }

  // Horizontal: one row for each bar, the label on the left, the value at the end of the bar.
  const rowHeight = (ctx.bottom - top) / bars.length;
  const labelHeight = Math.max(...bars.map((bar) => linesHeight(textOf(ctx, bar.label))));
  if (rowHeight < labelHeight || rowHeight < Math.round(0.05 * ctx.height)) {
    cannotDraw("the bars and their labels do not fit above the caption area.");
  }
  const labelWidth = 0.3 * ctx.W;
  const space = Math.round(0.015 * ctx.W);
  const valueSize = Math.min(...bars.map((bar) => fitNumber(bar.display, ctx.bodySize, 0.2 * ctx.W)));
  const valueWidth = Math.ceil(Math.max(...bars.map((bar) => numberWidth(ctx, bar.ref, valueSize))));
  const areaLeft = ctx.left + labelWidth + space + (lowest < 0 ? valueWidth + space : 0);
  const areaRight = ctx.right - valueWidth - space;
  const scale = (areaRight - areaLeft) / range;
  const baseline = Math.round(areaLeft - lowest * scale);
  const thickness = Math.round(
    Math.min(0.6 * rowHeight, MAX_HORIZONTAL_THICKNESS * ctx.height),
  );
  const first = bars[0]?.p ?? 0;

  return (
    <>
      {highlightPart}
      {first > 0 && (
        <div
          style={{
            position: "absolute",
            left: baseline - Math.floor(ctx.stroke / 2),
            top,
            width: ctx.stroke,
            height: ctx.bottom - top,
            background: ctx.theme.muted,
            opacity: first,
          }}
        />
      )}
      {bars.map((bar, index) => {
        const rowTop = top + index * rowHeight;
        const barTop = Math.round(rowTop + (rowHeight - thickness) / 2);
        const full = Math.abs(bar.value) * scale;
        const grown = Math.round(full * bar.p);
        const barLeft = bar.value >= 0 ? baseline : baseline - grown;
        const valueY = Math.round(rowTop + (rowHeight - textHeight(valueSize)) / 2);
        const valueX =
          bar.value >= 0 ? baseline + Math.round(full) + space : baseline - Math.round(full) - space;
        return (
          <div key={index}>
            <div
              style={{
                position: "absolute",
                left: barLeft,
                top: barTop,
                width: grown,
                height: thickness,
                background: colourOf(bar.emphasis),
                borderRadius: radius,
              }}
            />
            <Enter ctx={ctx} p={bar.p}>
              <Num
                ctx={ctx}
                item={bar.ref}
                size={valueSize}
                x={valueX}
                y={valueY}
                anchor={bar.value >= 0 ? "left" : "right"}
                p={bar.p}
                colour={ctx.theme.text}
              />
              <TextAt
                ctx={ctx}
                path={bar.label}
                colour={ctx.theme.muted}
                left={ctx.left}
                top={Math.round(
                  rowTop + (rowHeight - linesHeight(textOf(ctx, bar.label))) / 2,
                )}
                width={labelWidth}
                align="right"
              />
            </Enter>
          </div>
        );
      })}
    </>
  );
}
