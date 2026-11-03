import { useMemo } from "react";
import type { ReactNode } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import { useFontsReady } from "../fonts";
import { Background } from "../templates/Background";
import type { GraphicInput } from "../types";
import { Fx, enterProgress, exitProgress, presence } from "./effects";
import { layoutScene } from "./layout";
import type { Laid } from "./layout";
import { readScene } from "./scene";
import type { Element, Scene } from "./scene";
import { DrawBars, DrawLine } from "./Series";
import { DrawArrow, DrawHighlight, DrawRing } from "./Shapes";
import { DrawTable } from "./Table";
import { DrawBadge, DrawCounter, DrawNode, DrawText } from "./TextBlocks";
import type { BCtx } from "./ctx";

// How far the element an arrow or a highlight follows is on the screen, so that they appear after
// their target and leave with it. 1 when the element has no such target.
function targetsPresence(ctx: BCtx, frame: number, scene: Scene, element: Element): number {
  const ids =
    element.block === "arrow" ? [element.from, element.to] : element.block === "highlight" ? [element.target] : [];
  let share = 1;
  for (const id of ids) {
    const target = scene.elements.find((candidate) => candidate.id === id);
    if (target !== undefined) share = Math.min(share, presence(ctx, frame, target));
  }
  return share;
}

function Piece({
  ctx,
  frame,
  scene,
  element,
  entry,
}: {
  ctx: BCtx;
  frame: number;
  scene: Scene;
  element: Element;
  entry: Laid;
}) {
  const parts = enterProgress(ctx, frame, element);
  const effect = element.enter.effect;
  const own = Math.min(parts[0] ?? 0, targetsPresence(ctx, frame, scene, element));

  let drawn: ReactNode;
  if (entry.kind === "bar_series") {
    drawn = <DrawBars ctx={ctx} l={entry} effect={effect} p={parts} />;
  } else if (entry.kind === "line_series") {
    drawn = <DrawLine ctx={ctx} l={entry} effect={effect} p={parts} />;
  } else {
    let single: ReactNode = null;
    if (entry.kind === "text") single = <DrawText l={entry} effect={effect} p={own} />;
    else if (entry.kind === "counter") single = <DrawCounter l={entry} effect={effect} p={own} />;
    else if (entry.kind === "badge") single = <DrawBadge l={entry} effect={effect} p={own} />;
    else if (entry.kind === "node") single = <DrawNode ctx={ctx} l={entry} />;
    else if (entry.kind === "table") single = <DrawTable ctx={ctx} l={entry} />;
    else if (entry.kind === "arrow") single = <DrawArrow ctx={ctx} l={entry} effect={effect} p={own} />;
    else if (entry.kind === "highlight") single = <DrawHighlight ctx={ctx} l={entry} effect={effect} p={own} />;
    else single = <DrawRing ctx={ctx} l={entry} effect={effect} p={own} />;
    drawn = (
      <Fx ctx={ctx} effect={effect} p={own} box={entry.box}>
        {single}
      </Fx>
    );
  }

  // An element that is leaving takes its exit effect backwards from its finished look.
  const leaving = exitProgress(ctx, frame, element);
  if (element.exit !== undefined && leaving > 0) {
    return (
      <Fx ctx={ctx} effect={element.exit.effect} p={1 - leaving} box={entry.box}>
        {drawn}
      </Fx>
    );
  }
  return <>{drawn}</>;
}

// The `Blocks` composition (GFX-009): draws the block scene of the model, in `input`, over the
// resolved brief. Every element enters on its beat. A scene that cannot be drawn fails the render
// with a message.
export function Blocks(props: GraphicInput) {
  const frame = useCurrentFrame();
  const ready = useFontsReady();
  const scene = useMemo(() => readScene(props.input), [props.input]);
  const layout = useMemo(() => (ready ? layoutScene(props, scene) : null), [ready, props, scene]);
  const { theme } = props.resolved;
  if (layout === null) return <AbsoluteFill style={{ background: theme.background }} />;

  return (
    <AbsoluteFill>
      <Background theme={theme} width={props.width} height={props.height} />
      {scene.elements.map((element, index) => {
        const entry = layout.laid[index];
        if (entry === undefined) return null;
        return (
          <Piece
            key={element.id}
            ctx={layout.ctx}
            frame={frame}
            scene={scene}
            element={element}
            entry={entry}
          />
        );
      })}
    </AbsoluteFill>
  );
}
