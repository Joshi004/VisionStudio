import { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import { useFontsReady } from "../fonts";
import type { GraphicInput } from "../types";
import { Background } from "./Background";
import { BarComparison } from "./BarComparison";
import { BulletBuild } from "./BulletBuild";
import { FlowDiagram } from "./FlowDiagram";
import { KpiCard } from "./KpiCard";
import { enterOf, makeCtx } from "./layout";
import { LineTrend } from "./LineTrend";
import { readSpec } from "./spec";
import { Enter, TextAt } from "./Text";

// The `Templates` composition (GFX-007): draws the template spec of GFX-006 in `input`, over the
// resolved brief, following the look rules and the layout of §4.5.1. Text is drawn exactly as the
// spec laid it out. An input that cannot be drawn fails the render with a message.
export function Templates(props: GraphicInput) {
  const frame = useCurrentFrame();
  const ready = useFontsReady();
  const spec = useMemo(() => readSpec(props.input), [props.input]);
  const { theme } = props.resolved;
  if (!ready) return <AbsoluteFill style={{ background: theme.background }} />;

  const ctx = makeCtx(frame, props, spec);
  const titleBeat: string | undefined = spec.beats.title;

  return (
    <AbsoluteFill>
      <Background theme={theme} width={props.width} height={props.height} />
      {titleBeat !== undefined && spec.text["title"] !== undefined && (
        <Enter ctx={ctx} p={enterOf(ctx, titleBeat)}>
          <TextAt
            ctx={ctx}
            path="title"
            colour={theme.text}
            left={ctx.left}
            top={ctx.top}
            width={ctx.W}
            align="left"
          />
        </Enter>
      )}
      {spec.template === "kpi_card" && <KpiCard ctx={ctx} spec={spec} />}
      {spec.template === "bar_comparison" && <BarComparison ctx={ctx} spec={spec} />}
      {spec.template === "line_trend" && <LineTrend ctx={ctx} spec={spec} />}
      {spec.template === "flow_diagram" && <FlowDiagram ctx={ctx} spec={spec} />}
      {spec.template === "bullet_build" && <BulletBuild ctx={ctx} spec={spec} />}
    </AbsoluteFill>
  );
}
