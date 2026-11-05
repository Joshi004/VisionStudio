import { Fragment } from "react";

import { measureText, withAlpha } from "../templates/layout";
import type { Box } from "../types";
import { boxHeight, boxWidth, measureOf } from "./ctx";
import type { BCtx } from "./ctx";
import { Fx } from "./effects";
import { fitNumberIn, fitText, linesHeight, placeText } from "./fit";
import type { TextItem } from "./fit";
import { Item } from "./Item";
import type { BarSeriesEl, LineSeriesEl } from "./scene";

// The two blocks that show a series of values: `bar_series` and `line_series`. Every value is a
// part with a beat of its own, and every part has its own progress.

// The least a plot may be high, as a share of the video's height. Below it the layout reports
// that the series has no room.
const MIN_PLOT = 0.05;

// --- bar_series ----------------------------------------------------------------------------------

export type BarsLaid = {
  kind: "bar_series";
  id: string;
  box: Box;
  texts: TextItem[];
  orientation: "vertical" | "horizontal";
  // The finished bar of each value, the box of the whole part (bar, value and label), the colour,
  // and whether the value is above zero.
  bars: { box: Box; part: Box; colour: string; positive: boolean }[];
  // The line the bars start from.
  baseline: Box;
  radius: number;
  issues: string[];
};

export function layoutBars(ctx: BCtx, element: BarSeriesEl, box: Box): BarsLaid {
  const values = element.values.map((ref) => measureOf(ctx, ref));
  const count = values.length;
  const w = boxWidth(box);
  const h = boxHeight(box);
  const gap = Math.round(0.01 * ctx.height);
  const lowest = Math.min(0, ...values.map((item) => item.value));
  const highest = Math.max(0, ...values.map((item) => item.value));
  const range = highest - lowest || 1;
  const emphasised = new Set(element.emphasis ?? []);
  const anyEmphasis = element.values.some((ref) => emphasised.has(ref));
  const colourFor = (ref: string) =>
    !anyEmphasis || emphasised.has(ref) ? ctx.theme.accent : ctx.theme.muted;
  const issues: string[] = [];
  const horizontal = element.orientation === "horizontal";

  const slot = w / count;
  const rowHeight = h / count;
  const labelSpace = horizontal ? 0.3 * w : slot;
  const labelHeightSpace = horizontal ? rowHeight : 0.3 * h;
  const labelFits = element.labels.map((label) =>
    fitText(label, "text", ctx.bodySize, labelSpace, labelHeightSpace, 2),
  );
  const labelSize = Math.min(...labelFits.map((fit) => fit.size));
  const valueSize = Math.min(
    ...values.map((item) =>
      fitNumberIn(item.display, ctx.bodySize, horizontal ? 0.2 * w : slot, horizontal ? rowHeight : h),
    ),
  );
  const valueHeight = Math.round(linesHeight(1, valueSize));

  const texts: TextItem[] = [];
  const bars: BarsLaid["bars"] = [];
  const radius = Math.max(2, Math.round(ctx.height / 270));
  let baseline: Box;

  if (!horizontal) {
    const labelRows = Math.max(...labelFits.map((fit) => fit.lines.length));
    const labelsHeight = Math.round(linesHeight(labelRows, labelSize)) + gap;
    const labelTop = box.bottom - labelsHeight + gap;
    const valueRow = valueHeight + gap;
    const plotTop = box.top + valueRow;
    const plotBottom = labelTop - gap - (lowest < 0 ? valueRow : 0);
    if (plotBottom - plotTop < Math.round(MIN_PLOT * ctx.height)) {
      issues.push("The bars have no room: the region is too small for the bars, values and labels.");
    }
    const scale = Math.max(plotBottom - plotTop, 1) / range;
    const base = Math.round(plotTop + highest * scale);
    const barWidth = Math.round(Math.min(0.6 * slot, 0.2 * w));
    baseline = {
      left: box.left,
      top: base - Math.floor(ctx.stroke / 2),
      right: box.right,
      bottom: base - Math.floor(ctx.stroke / 2) + ctx.stroke,
    };
    values.forEach((item, index) => {
      const ref = element.values[index] as string;
      const centre = box.left + (index + 0.5) * slot;
      const full = Math.round(Math.abs(item.value) * scale);
      const positive = item.value >= 0;
      const bar: Box = {
        left: Math.round(centre - barWidth / 2),
        right: Math.round(centre - barWidth / 2) + barWidth,
        top: positive ? base - full : base,
        bottom: positive ? base : base + full,
      };
      const valueTop = positive ? bar.top - gap - valueHeight : bar.bottom + gap;
      const area = { left: box.left + index * slot, right: box.left + (index + 1) * slot };
      const fit = labelFits[index] as ReturnType<typeof fitText>;
      texts.push(
        {
          part: `value.${index}`,
          group: index,
          text: item.display,
          font: "display",
          size: valueSize,
          lines: [item.display],
          box: placeText([item.display], "display", valueSize, "center", area, valueTop),
          align: "center",
          colour: ctx.theme.text,
          counts: item.unit !== "none",
        },
        {
          part: `label.${index}`,
          group: index,
          text: element.labels[index] as string,
          font: "text",
          size: labelSize,
          lines: fit.lines,
          box: placeText(fit.lines, "text", labelSize, "center", area, labelTop),
          align: "center",
          colour: ctx.theme.muted,
          counts: false,
        },
      );
      bars.push({
        box: bar,
        part: { left: Math.round(area.left), right: Math.round(area.right), top: box.top, bottom: box.bottom },
        colour: colourFor(ref),
        positive,
      });
    });
  } else {
    const space = Math.round(0.015 * w);
    const valueWidth = Math.ceil(
      Math.max(...values.map((item) => measureText(item.display, "display", valueSize))),
    );
    const areaLeft = box.left + 0.3 * w + space + (lowest < 0 ? valueWidth + space : 0);
    const areaRight = box.right - valueWidth - space;
    if (areaRight - areaLeft < 0.1 * w) {
      issues.push("The bars have no room: the region is too narrow for the bars, values and labels.");
    }
    const scale = Math.max(areaRight - areaLeft, 1) / range;
    const base = Math.round(areaLeft - lowest * scale);
    const thickness = Math.round(Math.min(0.6 * rowHeight, 0.09 * ctx.height));
    baseline = {
      left: base - Math.floor(ctx.stroke / 2),
      top: box.top,
      right: base - Math.floor(ctx.stroke / 2) + ctx.stroke,
      bottom: box.bottom,
    };
    values.forEach((item, index) => {
      const ref = element.values[index] as string;
      const rowTop = box.top + index * rowHeight;
      const barTop = Math.round(rowTop + (rowHeight - thickness) / 2);
      const full = Math.round(Math.abs(item.value) * scale);
      const positive = item.value >= 0;
      const bar: Box = {
        left: positive ? base : base - full,
        right: positive ? base + full : base,
        top: barTop,
        bottom: barTop + thickness,
      };
      const fit = labelFits[index] as ReturnType<typeof fitText>;
      const valueY = rowTop + (rowHeight - valueHeight) / 2;
      const valueArea = positive
        ? { left: bar.right + space, right: bar.right + space + valueWidth }
        : { left: bar.left - space - valueWidth, right: bar.left - space };
      texts.push(
        {
          part: `value.${index}`,
          group: index,
          text: item.display,
          font: "display",
          size: valueSize,
          lines: [item.display],
          box: placeText([item.display], "display", valueSize, positive ? "left" : "right", valueArea, valueY),
          align: positive ? "left" : "right",
          colour: ctx.theme.text,
          counts: item.unit !== "none",
        },
        {
          part: `label.${index}`,
          group: index,
          text: element.labels[index] as string,
          font: "text",
          size: labelSize,
          lines: fit.lines,
          box: placeText(
            fit.lines,
            "text",
            labelSize,
            "right",
            { left: box.left, right: box.left + 0.3 * w },
            rowTop + (rowHeight - linesHeight(fit.lines.length, labelSize)) / 2,
          ),
          align: "right",
          colour: ctx.theme.muted,
          counts: false,
        },
      );
      bars.push({
        box: bar,
        part: { left: box.left, right: box.right, top: Math.round(rowTop), bottom: Math.round(rowTop + rowHeight) },
        colour: colourFor(ref),
        positive,
      });
    });
  }
  return {
    kind: "bar_series",
    id: element.id,
    box,
    texts,
    orientation: element.orientation,
    bars,
    baseline,
    radius,
    issues,
  };
}

export function DrawBars({
  ctx,
  l,
  effect,
  p,
}: {
  ctx: BCtx;
  l: BarsLaid;
  effect: string;
  p: number[];
}) {
  const first = Math.max(0, ...p);
  const grow = effect === "grow";
  const vertical = l.orientation === "vertical";
  return (
    <>
      {first > 0 && (
        <div
          style={{
            position: "absolute",
            left: l.baseline.left,
            top: l.baseline.top,
            width: boxWidth(l.baseline),
            height: boxHeight(l.baseline),
            background: ctx.theme.muted,
            opacity: Math.min(1, first),
          }}
        />
      )}
      {l.bars.map((bar, index) => {
        const progress = p[index] ?? 0;
        // A growing bar is as long as its progress; any other effect shows the whole bar.
        const share = grow ? progress : 1;
        const shown: Box = { ...bar.box };
        if (vertical) {
          const full = boxHeight(bar.box);
          if (bar.positive) shown.top = bar.box.bottom - Math.round(full * share);
          else shown.bottom = bar.box.top + Math.round(full * share);
        } else {
          const full = boxWidth(bar.box);
          if (bar.positive) shown.right = bar.box.left + Math.round(full * share);
          else shown.left = bar.box.right - Math.round(full * share);
        }
        const rect = (
          <div
            style={{
              position: "absolute",
              left: shown.left,
              top: shown.top,
              width: boxWidth(shown),
              height: boxHeight(shown),
              background: bar.colour,
              borderRadius: l.radius,
            }}
          />
        );
        const texts = l.texts
          .filter((item) => item.group === index)
          .map((item) => <Item key={item.part} item={item} count={grow ? progress : 1} />);
        if (grow) {
          return (
            <Fragment key={index}>
              {progress > 0 && rect}
              <Fx ctx={ctx} effect="fade" p={progress} box={bar.part}>
                {texts}
              </Fx>
            </Fragment>
          );
        }
        return (
          <Fx key={index} ctx={ctx} effect={effect} p={progress} box={bar.part}>
            {rect}
            {texts}
          </Fx>
        );
      })}
    </>
  );
}

// --- line_series ---------------------------------------------------------------------------------

type Point = { x: number; y: number };

export type LineLaid = {
  kind: "line_series";
  id: string;
  box: Box;
  texts: TextItem[];
  points: Point[];
  plot: { top: number; bottom: number };
  thickness: number;
  dot: number;
  area: boolean;
  issues: string[];
};

export function layoutLine(ctx: BCtx, element: LineSeriesEl, box: Box): LineLaid {
  const values = element.values.map((ref) => measureOf(ctx, ref));
  const count = values.length;
  const w = boxWidth(box);
  const h = boxHeight(box);
  const slot = w / count;
  const gap = Math.round(0.01 * ctx.height);
  const dot = Math.round(0.008 * ctx.height);
  const labelFits = element.labels.map((label) =>
    fitText(label, "text", ctx.bodySize, slot, 0.3 * h, 2),
  );
  const labelSize = Math.min(...labelFits.map((fit) => fit.size));
  const valueSize = Math.min(...values.map((item) => fitNumberIn(item.display, ctx.bodySize, slot, h)));
  const valueRow = Math.round(linesHeight(1, valueSize)) + gap;
  const labelRows = Math.max(...labelFits.map((fit) => fit.lines.length));
  const labelTop = box.bottom - Math.round(linesHeight(labelRows, labelSize));
  const plotTop = box.top + valueRow;
  const plotBottom = labelTop - gap;
  const issues: string[] = [];
  if (plotBottom - plotTop < Math.round(MIN_PLOT * ctx.height)) {
    issues.push("The line has no room: the region is too small for the line, values and labels.");
  }
  const low = Math.min(...values.map((item) => item.value));
  const high = Math.max(...values.map((item) => item.value));
  const spread = high - low || Math.max(1, 0.1 * Math.abs(high));
  const axisLow = low - 0.1 * spread;
  const axisHigh = high + 0.1 * spread;
  const plotHeight = Math.max(plotBottom - plotTop, 1);
  const points: Point[] = values.map((item, index) => ({
    x: box.left + (index + 0.5) * slot,
    y: plotBottom - ((item.value - axisLow) / (axisHigh - axisLow)) * plotHeight,
  }));
  const texts: TextItem[] = [];
  values.forEach((item, index) => {
    const here = points[index] as Point;
    const area = { left: box.left + index * slot, right: box.left + (index + 1) * slot };
    const fit = labelFits[index] as ReturnType<typeof fitText>;
    texts.push(
      {
        part: `value.${index}`,
        group: index,
        text: item.display,
        font: "display",
        size: valueSize,
        lines: [item.display],
        box: placeText(
          [item.display],
          "display",
          valueSize,
          "center",
          area,
          here.y - dot - gap - linesHeight(1, valueSize),
        ),
        align: "center",
        colour: ctx.theme.text,
        counts: item.unit !== "none",
      },
      {
        part: `label.${index}`,
        group: index,
        text: element.labels[index] as string,
        font: "text",
        size: labelSize,
        lines: fit.lines,
        box: placeText(fit.lines, "text", labelSize, "center", area, labelTop),
        align: "center",
        colour: ctx.theme.muted,
        counts: false,
      },
    );
  });
  return {
    kind: "line_series",
    id: element.id,
    box,
    texts,
    points,
    plot: { top: plotTop, bottom: plotBottom },
    thickness: Math.max(3, Math.round(0.004 * ctx.height)),
    dot,
    area: element.area === true,
    issues,
  };
}

function between(from: Point, to: Point, share: number): Point {
  return { x: from.x + (to.x - from.x) * share, y: from.y + (to.y - from.y) * share };
}

export function DrawLine({
  ctx,
  l,
  effect,
  p,
}: {
  ctx: BCtx;
  l: LineLaid;
  effect: string;
  p: number[];
}) {
  const draw = effect === "draw";
  const grid = [0, 0.5, 1].map((share) =>
    Math.round(l.plot.top + share * (l.plot.bottom - l.plot.top)),
  );
  // What of the line has been drawn: the first point once its beat has come, then each segment as
  // far as its point's beat has progressed (a `fade` shows the whole segment, fading in).
  const reached: Point[] = [];
  l.points.forEach((here, index) => {
    const progress = p[index] ?? 0;
    const before = l.points[index - 1];
    if (progress <= 0) return;
    reached.push(
      index === 0 || before === undefined ? here : draw ? between(before, here, progress) : here,
    );
  });
  const lastShare = Math.max(0, ...p.slice(-1));
  const first = reached[0];
  const last = reached[reached.length - 1];
  return (
    <>
      <svg width={ctx.width} height={ctx.height} style={{ position: "absolute", left: 0, top: 0 }}>
        {grid.map((y) => (
          <line
            key={y}
            x1={l.box.left}
            x2={l.box.right}
            y1={y}
            y2={y}
            stroke={ctx.theme.surface}
            strokeWidth={ctx.stroke}
          />
        ))}
        {l.area && first !== undefined && last !== undefined && (
          <polygon
            points={[
              `${first.x},${l.plot.bottom}`,
              ...reached.map((point) => `${point.x},${point.y}`),
              `${last.x},${l.plot.bottom}`,
            ].join(" ")}
            fill={withAlpha(ctx.theme.accent, 0.2 * (draw ? 1 : lastShare))}
          />
        )}
        {l.points.map((here, index) => {
          const before = l.points[index - 1];
          const progress = p[index] ?? 0;
          if (index === 0 || before === undefined || progress <= 0) return null;
          const end = draw ? between(before, here, progress) : here;
          return (
            <line
              key={index}
              x1={before.x}
              y1={before.y}
              x2={end.x}
              y2={end.y}
              stroke={ctx.theme.accent}
              strokeWidth={l.thickness}
              strokeLinecap="round"
              opacity={draw ? 1 : progress}
            />
          );
        })}
        {l.points.map((here, index) => {
          const progress = p[index] ?? 0;
          if (progress <= 0) return null;
          return (
            <circle
              key={index}
              cx={here.x}
              cy={here.y}
              r={l.dot * (draw ? progress : 1)}
              fill={ctx.theme.accent}
              opacity={progress}
            />
          );
        })}
      </svg>
      {l.points.map((here, index) => (
        <Fx key={index} ctx={ctx} effect="fade" p={p[index] ?? 0} box={l.box}>
          {l.texts
            .filter((item) => item.group === index)
            .map((item) => (
              <Item key={item.part} item={item} />
            ))}
        </Fx>
      ))}
    </>
  );
}
