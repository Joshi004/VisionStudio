// How a block enters and leaves (§4.5.2, "Effects"). All timing is the templates' (`progressAt`:
// ease-out cubic over 12, 18 or 24 frames, already above 0 on the beat's frame), so it depends on
// the frame number only and two renders of one scene are identical.
import type { ReactNode } from "react";

import type { Box } from "../types";
import { progressAt } from "../templates/motion";
import { beatFrame } from "./ctx";
import type { BCtx } from "./ctx";
import type { Element } from "./scene";

// The effects that only change how a whole block is shown. The others (`grow`, `draw`,
// `count_up`, `typewriter`) are drawn by the block itself from the progress.
export const WRAP_EFFECTS = ["fade", "slide_up", "slide_left", "pop"];

export function enterBeats(element: Element): string[] {
  const { enter } = element;
  return enter.beats ?? (enter.beat === undefined ? [] : [enter.beat]);
}

// How far each part of the block has come at `frame`, from 0 to 1. A block that enters once has
// one part; a series has one for each of its values.
export function enterProgress(ctx: BCtx, frame: number, element: Element): number[] {
  return enterBeats(element).map((beat) => progressAt(frame, beatFrame(ctx, beat), ctx.motion));
}

// How far the block has left, from 0 (still there) to 1 (gone).
export function exitProgress(ctx: BCtx, frame: number, element: Element): number {
  if (element.exit === undefined) return 0;
  return progressAt(frame, beatFrame(ctx, element.exit.beat), ctx.motion);
}

// How much of the block is on the screen: 0 before it enters and after it has left.
export function presence(ctx: BCtx, frame: number, element: Element): number {
  const entered = Math.max(0, ...enterProgress(ctx, frame, element));
  return Math.min(entered, 1 - exitProgress(ctx, frame, element));
}

// A part that enters or leaves with a wrapping effect, as far as `p` has come. It draws nothing
// at 0. The other effects pass their children through unchanged.
export function Fx({
  ctx,
  effect,
  p,
  box,
  children,
}: {
  ctx: BCtx;
  effect: string;
  p: number;
  box: Box;
  children: ReactNode;
}) {
  if (p <= 0) return null;
  let opacity = 1;
  let transform = "none";
  if (effect === "fade") {
    opacity = p;
  } else if (effect === "slide_up") {
    opacity = p;
    transform = `translateY(${(1 - p) * 0.03 * ctx.height}px)`;
  } else if (effect === "slide_left") {
    opacity = p;
    transform = `translateX(${(1 - p) * 0.05 * ctx.height}px)`;
  } else if (effect === "pop") {
    opacity = p;
    transform = `scale(${0.6 + 0.4 * p})`;
  }
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: ctx.width,
        height: ctx.height,
        opacity,
        transform,
        transformOrigin: `${(box.left + box.right) / 2}px ${(box.top + box.bottom) / 2}px`,
      }}
    >
      {children}
    </div>
  );
}
