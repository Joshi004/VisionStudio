import {
  cannotDraw,
  contentTop,
  enterOf,
  fitNumber,
  linesHeight,
  measureOf,
  textHeight,
  textOf,
  withAlpha,
} from "./layout";
import type { Ctx } from "./layout";
import type { LineSpec } from "./spec";
import { Enter, Num, Pill, pillSize, TextAt } from "./Text";

type Point = { x: number; y: number };

function between(from: Point, to: Point, p: number): Point {
  return { x: from.x + (to.x - from.x) * p, y: from.y + (to.y - from.y) * p };
}

// Values over time, three to twelve points (§4.5.1). The axis is fitted to the data with 10
// percent padding and has faint grid lines but no tick numbers (every number on screen comes from
// the line, G-7): each point shows its own value instead. The line draws through each point as its
// beat arrives. `area` also fills under the line, revealed with it.
export function LineTrend({ ctx, spec }: { ctx: Ctx; spec: LineSpec }) {
  const { fields, beats } = spec;
  const points = fields.points.map((point, index) => {
    const beat = beats.points[index];
    if (beat === undefined) cannotDraw(`point ${index + 1} has no beat.`);
    const measure = measureOf(ctx, point.value);
    return {
      value: measure.value,
      display: measure.display,
      ref: point.value,
      p: enterOf(ctx, beat),
      label: `points.${index}.label`,
    };
  });
  const count = points.length;
  const slot = ctx.W / count;
  const gap = Math.round(0.01 * ctx.height);

  const endLabel = fields.end_label;
  const pill = endLabel === undefined ? null : pillSize(ctx, endLabel);
  const valueSize = Math.min(...points.map((point) => fitNumber(point.display, ctx.bodySize, slot)));
  const valueRow = Math.round(textHeight(valueSize)) + gap;
  const labelsHeight =
    Math.round(Math.max(...points.map((point) => linesHeight(textOf(ctx, point.label))))) + gap;
  const labelTop = ctx.bottom - labelsHeight + gap;

  const plotTop =
    contentTop(ctx) + (pill === null ? 0 : pill.height + Math.round(0.02 * ctx.height)) + valueRow;
  const plotBottom = labelTop - gap;
  if (plotBottom - plotTop < Math.round(0.15 * ctx.height)) {
    cannotDraw("the line, its values and its labels do not fit above the caption area.");
  }

  // The range of the axis: the data with 10 percent of its spread on both sides.
  const low = Math.min(...points.map((point) => point.value));
  const high = Math.max(...points.map((point) => point.value));
  const spread = high - low || Math.max(1, 0.1 * Math.abs(high));
  const axisLow = low - 0.1 * spread;
  const axisHigh = high + 0.1 * spread;
  const at: Point[] = points.map((point, index) => ({
    x: ctx.left + (index + 0.5) * slot,
    y: plotBottom - ((point.value - axisLow) / (axisHigh - axisLow)) * (plotBottom - plotTop),
  }));

  // What of the line has been drawn: the first point once its beat has come, then each segment as
  // far as its point's beat has progressed.
  const reached: Point[] = [];
  points.forEach((point, index) => {
    const here = at[index];
    const before = at[index - 1];
    if (here === undefined || point.p <= 0) return;
    reached.push(index === 0 || before === undefined ? here : between(before, here, point.p));
  });

  const thickness = Math.max(3, Math.round(0.004 * ctx.height));
  const dot = Math.round(0.008 * ctx.height);
  const grid = [0, 0.5, 1].map((share) => Math.round(plotTop + share * (plotBottom - plotTop)));
  const last = reached[reached.length - 1];
  const first = reached[0];
  const endBeat = beats.end_label;

  return (
    <>
      <svg
        width={ctx.width}
        height={ctx.height}
        style={{ position: "absolute", left: 0, top: 0 }}
      >
        {grid.map((y) => (
          <line
            key={y}
            x1={ctx.left}
            x2={ctx.right}
            y1={y}
            y2={y}
            stroke={ctx.theme.surface}
            strokeWidth={ctx.stroke}
          />
        ))}
        {spec.variant === "area" && first !== undefined && last !== undefined && (
          <polygon
            points={[
              `${first.x},${plotBottom}`,
              ...reached.map((point) => `${point.x},${point.y}`),
              `${last.x},${plotBottom}`,
            ].join(" ")}
            fill={withAlpha(ctx.theme.accent, 0.2)}
          />
        )}
        {reached.length > 1 && (
          <polyline
            points={reached.map((point) => `${point.x},${point.y}`).join(" ")}
            fill="none"
            stroke={ctx.theme.accent}
            strokeWidth={thickness}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {points.map((point, index) => {
          const here = at[index];
          if (here === undefined || point.p <= 0) return null;
          return (
            <circle
              key={index}
              cx={here.x}
              cy={here.y}
              r={dot * point.p}
              fill={ctx.theme.accent}
              opacity={point.p}
            />
          );
        })}
      </svg>
      {points.map((point, index) => {
        const here = at[index];
        if (here === undefined) return null;
        return (
          <Enter key={index} ctx={ctx} p={point.p}>
            <Num
              ctx={ctx}
              item={point.ref}
              size={valueSize}
              x={here.x}
              y={Math.round(here.y - dot - gap - textHeight(valueSize))}
              anchor="center"
              p={point.p}
              colour={ctx.theme.text}
            />
            <TextAt
              ctx={ctx}
              path={point.label}
              colour={ctx.theme.muted}
              left={ctx.left + index * slot}
              top={labelTop}
              width={slot}
              align="center"
            />
          </Enter>
        );
      })}
      {endLabel !== undefined && endBeat !== undefined && (
        <Enter ctx={ctx} p={enterOf(ctx, endBeat)}>
          <Pill
            ctx={ctx}
            item={endLabel}
            right={ctx.right}
            top={contentTop(ctx)}
            p={enterOf(ctx, endBeat)}
          />
        </Enter>
      )}
    </>
  );
}
