import type { Box } from "../types";
import { boxHeight, boxWidth, cornerRadius } from "./ctx";
import type { BCtx } from "./ctx";
import type { TextItem } from "./fit";
import type { PanelEl } from "./scene";

// The `panel` block (CMO-004, callouts only): a box in `surface` with the callout look's corners,
// no text, drawn under the elements that overlap it so that their text stays readable over video.

export type PanelLaid = {
  kind: "panel";
  id: string;
  box: Box;
  texts: TextItem[];
  fill: string;
  opacity: number;
  radius: number;
};

export function layoutPanel(ctx: BCtx, element: PanelEl, box: Box): PanelLaid {
  return {
    kind: "panel",
    id: element.id,
    box,
    texts: [],
    fill: ctx.theme.surface,
    opacity: ctx.panelOpacity,
    radius: cornerRadius(ctx, box) ?? 0,
  };
}

export function DrawPanel({ l }: { l: PanelLaid }) {
  return (
    <div
      style={{
        position: "absolute",
        left: l.box.left,
        top: l.box.top,
        width: boxWidth(l.box),
        height: boxHeight(l.box),
        background: l.fill,
        opacity: l.opacity,
        borderRadius: l.radius,
      }}
    />
  );
}
