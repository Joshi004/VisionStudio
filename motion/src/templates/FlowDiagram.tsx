import { cannotDraw, contentTop, enterOf, linesHeight, textOf } from "./layout";
import type { Ctx } from "./layout";
import type { FlowSpec } from "./spec";
import { Enter, TextAt } from "./Text";

// Two to six steps in a chain (§4.5.1). A node is a rounded `surface` box with an `accent` border;
// the arrow to a node draws in as the node arrives. In `horizontal` the nodes share the safe width
// with a gap of 6 percent of it; in `vertical` they are 0.7 W / 0.85 wide and centred, and the gaps
// shrink (from 5 percent of the height down to 2 percent) before the layout is refused.
export function FlowDiagram({ ctx, spec }: { ctx: Ctx; spec: FlowSpec }) {
  const nodes = spec.fields.nodes.map((node, index) => ({
    path: `nodes.${index}.label`,
    p: enterOf(ctx, node.beat),
  }));
  const count = nodes.length;
  const horizontal = spec.variant === "horizontal";
  const top = contentTop(ctx);
  const available = ctx.bottom - top;

  // Every node is as high as the tallest label needs, plus 0.35 of its size above and below.
  const textHeights = nodes.map((node) => linesHeight(textOf(ctx, node.path)));
  const tallest = Math.max(...nodes.map((node) => textOf(ctx, node.path).size));
  const padding = Math.round(0.35 * tallest);
  const nodeHeight = Math.round(Math.max(...textHeights)) + 2 * padding;

  const nodeWidth = horizontal
    ? (ctx.W - (count - 1) * 0.06 * ctx.W) / count
    : (0.7 * ctx.W) / 0.85;
  const border = Math.max(2, Math.round(ctx.height / 360));
  const radius = Math.round(0.3 * tallest);

  let gap: number;
  let originX: number;
  let originY: number;
  if (horizontal) {
    gap = 0.06 * ctx.W;
    originX = ctx.left;
    if (nodeHeight > available) cannotDraw("the steps do not fit above the caption area.");
    originY = top + (available - nodeHeight) / 2;
  } else {
    gap = Math.min(
      Math.round(0.05 * ctx.height),
      (available - count * nodeHeight) / (count - 1),
    );
    if (gap < Math.round(0.02 * ctx.height)) {
      cannotDraw("the steps do not fit above the caption area.");
    }
    originX = ctx.left + (ctx.W - nodeWidth) / 2;
    originY = top + (available - (count * nodeHeight + (count - 1) * gap)) / 2;
  }

  const place = (index: number) => ({
    x: horizontal ? originX + index * (nodeWidth + gap) : originX,
    y: horizontal ? originY : originY + index * (nodeHeight + gap),
  });

  const head = Math.round(0.012 * ctx.height);
  const thickness = Math.max(2, Math.round(ctx.height / 270));

  return (
    <>
      <svg
        width={ctx.width}
        height={ctx.height}
        style={{ position: "absolute", left: 0, top: 0 }}
      >
        {nodes.map((node, index) => {
          if (index === 0 || node.p <= 0) return null;
          const from = place(index - 1);
          const to = place(index);
          // The arrow runs across the gap and keeps 15 percent of it free at both ends.
          const margin = 0.15 * gap;
          const x1 = horizontal ? from.x + nodeWidth + margin : from.x + nodeWidth / 2;
          const y1 = horizontal ? from.y + nodeHeight / 2 : from.y + nodeHeight + margin;
          const x2 = horizontal ? to.x - margin : to.x + nodeWidth / 2;
          const y2 = horizontal ? to.y + nodeHeight / 2 : to.y - margin;
          const tipX = x1 + (x2 - x1) * node.p;
          const tipY = y1 + (y2 - y1) * node.p;
          const wing = head * 0.7;
          const arrowhead = horizontal
            ? `${tipX},${tipY} ${tipX - head},${tipY - wing} ${tipX - head},${tipY + wing}`
            : `${tipX},${tipY} ${tipX - wing},${tipY - head} ${tipX + wing},${tipY - head}`;
          // The shaft stops at the base of the head.
          const shaftX = horizontal ? tipX - head : tipX;
          const shaftY = horizontal ? tipY : tipY - head;
          return (
            <g key={index} opacity={node.p}>
              <line
                x1={x1}
                y1={y1}
                x2={Math.max(x1, shaftX)}
                y2={Math.max(y1, shaftY)}
                stroke={ctx.theme.muted}
                strokeWidth={thickness}
                strokeLinecap="round"
              />
              <polygon points={arrowhead} fill={ctx.theme.muted} />
            </g>
          );
        })}
      </svg>
      {nodes.map((node, index) => {
        const at = place(index);
        const label = textOf(ctx, node.path);
        return (
          <Enter key={index} ctx={ctx} p={node.p}>
            <div
              style={{
                position: "absolute",
                left: Math.round(at.x),
                top: Math.round(at.y),
                width: Math.round(nodeWidth),
                height: nodeHeight,
                boxSizing: "border-box",
                background: ctx.theme.surface,
                border: `${border}px solid ${ctx.theme.accent}`,
                borderRadius: radius,
              }}
            />
            <TextAt
              ctx={ctx}
              path={node.path}
              colour={ctx.theme.text}
              left={Math.round(at.x)}
              top={Math.round(at.y + (nodeHeight - linesHeight(label)) / 2)}
              width={Math.round(nodeWidth)}
              align="center"
            />
          </Enter>
        );
      })}
    </>
  );
}
