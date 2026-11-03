import {
  cannotDraw,
  changeColour,
  contentTop,
  enterOf,
  fitNumber,
  linesHeight,
  measureOf,
  textHeight,
  textOf,
} from "./layout";
import type { Ctx } from "./layout";
import type { KpiSpec } from "./spec";
import { Enter, Num, TextAt } from "./Text";

// One big number, with a change and a caption (§4.5.1). `center` stacks the three in the middle of
// the content box. `split` puts the number on the left half, and the change and the caption on
// the right half; each half is centred vertically.
export function KpiCard({ ctx, spec }: { ctx: Ctx; spec: KpiSpec }) {
  const { fields, beats } = spec;
  const split = spec.variant === "split";
  const top = contentTop(ctx);
  const available = ctx.bottom - top;
  const gap = Math.round(0.02 * ctx.height);

  // The number is 14 percent of the height (landscape) or 7 percent (portrait); in `split` it
  // keeps a tenth of the left half free. It is made smaller when it does not fit.
  const space = split ? (ctx.W / 2) * 0.9 : ctx.W;
  const valueBase = Math.round((ctx.landscape ? 0.14 : 0.07) * ctx.height);
  const valueSize = fitNumber(measureOf(ctx, fields.value).display, valueBase, space);
  const valueHeight = textHeight(valueSize);

  const change = fields.change;
  const changeSize =
    change === undefined ? 0 : fitNumber(measureOf(ctx, change).display, ctx.titleSize, space);
  const captionHeight = fields.caption === undefined ? 0 : linesHeight(textOf(ctx, "caption"));

  const sideHeight =
    (change === undefined ? 0 : textHeight(changeSize)) +
    (change !== undefined && fields.caption !== undefined ? gap : 0) +
    captionHeight;
  const stackHeight = valueHeight + (sideHeight > 0 ? gap + sideHeight : 0);
  if ((split ? Math.max(valueHeight, sideHeight) : stackHeight) > available) {
    cannotDraw("the number, its change and its caption do not fit above the caption area.");
  }

  const centreX = ctx.left + ctx.W / 2;
  const valueX = split ? ctx.left : centreX;
  const valueY = Math.round(
    split ? top + (available - valueHeight) / 2 : top + (available - stackHeight) / 2,
  );
  const sideX = split ? ctx.left + ctx.W / 2 : centreX;
  let sideY = Math.round(
    split ? top + (available - sideHeight) / 2 : valueY + valueHeight + gap,
  );

  const valueP = enterOf(ctx, beats.value);
  const changeY = sideY;
  if (change !== undefined) sideY += Math.round(textHeight(changeSize) + gap);
  const sign = change === undefined ? 0 : measureOf(ctx, change).value;

  return (
    <>
      <Enter ctx={ctx} p={valueP}>
        <Num
          ctx={ctx}
          item={fields.value}
          size={valueSize}
          x={valueX}
          y={valueY}
          anchor={split ? "left" : "center"}
          p={valueP}
          colour={ctx.theme.text}
        />
      </Enter>
      {change !== undefined && beats.change !== undefined && (
        <Enter ctx={ctx} p={enterOf(ctx, beats.change)}>
          <Num
            ctx={ctx}
            item={change}
            size={changeSize}
            x={sideX}
            y={changeY}
            anchor={split ? "left" : "center"}
            p={enterOf(ctx, beats.change)}
            colour={changeColour(ctx, sign)}
          />
        </Enter>
      )}
      {fields.caption !== undefined && beats.caption !== undefined && (
        <Enter ctx={ctx} p={enterOf(ctx, beats.caption)}>
          <TextAt
            ctx={ctx}
            path="caption"
            colour={ctx.theme.muted}
            left={split ? sideX : ctx.left}
            top={sideY}
            width={split ? ctx.W / 2 : ctx.W}
            align={split ? "left" : "center"}
          />
        </Enter>
      )}
    </>
  );
}
