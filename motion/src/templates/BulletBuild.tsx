import { cannotDraw, contentTop, enterOf, linesHeight, textOf } from "./layout";
import type { Ctx } from "./layout";
import type { BulletSpec } from "./spec";
import { Enter, TextAt } from "./Text";

// A few points that build up one by one, or one short sentence shown large (§4.5.1). In a `list`
// the items stack from the top of the content box, each with an `accent` dot, and the text starts
// at L + 0.08 W (the `0.92 W` space the text was fitted to). A `statement` is one centred line in
// the display font, in the middle of the content box.
export function BulletBuild({ ctx, spec }: { ctx: Ctx; spec: BulletSpec }) {
  const items = spec.fields.items.map((item, index) => ({
    path: `items.${index}.text`,
    p: enterOf(ctx, item.beat),
  }));
  const top = contentTop(ctx);
  const available = ctx.bottom - top;

  if (spec.variant === "statement") {
    const item = items[0];
    if (item === undefined) cannotDraw("the statement has no item.");
    const height = linesHeight(textOf(ctx, item.path));
    if (height > available) cannotDraw("the statement does not fit above the caption area.");
    return (
      <Enter ctx={ctx} p={item.p}>
        <TextAt
          ctx={ctx}
          path={item.path}
          colour={ctx.theme.text}
          left={ctx.left}
          top={Math.round(top + (available - height) / 2)}
          width={ctx.W}
          align="center"
        />
      </Enter>
    );
  }

  const heights = items.map((item) => linesHeight(textOf(ctx, item.path)));
  const sizes = items.map((item) => textOf(ctx, item.path).size);
  const gaps = sizes.map((size) => Math.round(0.6 * size));
  let total = heights.reduce((sum, height) => sum + height, 0);
  total += gaps.slice(0, -1).reduce((sum, gap) => sum + gap, 0);
  if (total > available) cannotDraw("the items do not fit above the caption area.");

  let y = top;
  return (
    <>
      {items.map((item, index) => {
        const layout = textOf(ctx, item.path);
        const itemTop = Math.round(y);
        y += (heights[index] ?? 0) + (gaps[index] ?? 0);
        const radius = Math.round(0.18 * layout.size);
        return (
          <Enter key={index} ctx={ctx} p={item.p}>
            <div
              style={{
                position: "absolute",
                left: Math.round(ctx.left + 0.04 * ctx.W - radius),
                top: Math.round(itemTop + (layout.size * 1.2) / 2 - radius),
                width: 2 * radius,
                height: 2 * radius,
                borderRadius: radius,
                background: ctx.theme.accent,
              }}
            />
            <TextAt
              ctx={ctx}
              path={item.path}
              colour={ctx.theme.text}
              left={Math.round(ctx.left + 0.08 * ctx.W)}
              top={itemTop}
              width={Math.round(0.92 * ctx.W)}
              align="left"
            />
          </Enter>
        );
      })}
    </>
  );
}
