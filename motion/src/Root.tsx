import { Composition } from "remotion";
import type { CalculateMetadataFunction } from "remotion";

import { Blocks } from "./blocks/Blocks";
import { Callout } from "./callout/Callout";
import { layoutReport } from "./blocks/report";
import type { LayoutReport } from "./blocks/report";
import { readScene } from "./blocks/scene";
import { fontsLoaded } from "./fonts";
import { Generated } from "./generated/Generated";
import { TestCard } from "./TestCard";
import { Templates } from "./templates/Templates";
import type { GraphicInput, Resolved } from "./types";

// The size, frame rate and length of every video come from the input, so the frame count is
// exactly the one the backend asked for.
const metadata: CalculateMetadataFunction<GraphicInput> = ({ props }) => ({
  width: props.width,
  height: props.height,
  fps: props.fps,
  durationInFrames: props.frames,
});

// The props of `BlocksLayout` (GFX-009): the input of a `Blocks` render, the frames to report on,
// and the report that `calculateMetadata` makes of them. `POST /layout` reads it from the props
// that `selectComposition` returns, so the report is measured in the browser, with the fonts.
type LayoutProps = GraphicInput & { at_frames: number[]; report: LayoutReport | null };

const layoutMetadata: CalculateMetadataFunction<LayoutProps> = async ({ props }) => {
  await fontsLoaded;
  const report = layoutReport(props, readScene(props.input), props.at_frames);
  return {
    width: props.width,
    height: props.height,
    fps: props.fps,
    durationInFrames: props.frames,
    props: { ...props, report },
  };
};

const placeholder: Resolved = {
  width: 1920,
  height: 1080,
  fps: 24,
  frames: 72,
  facts: {},
  derived: {},
  beats: {},
  theme: {
    background: "#0B0F17",
    surface: "#161C28",
    text: "#FFFFFF",
    muted: "#9AA4B2",
    accent: "#4DA3FF",
    positive: "#2ED573",
    negative: "#FF4D4D",
    number: "#FFB000",
    background_style: "solid",
    motion: "snappy",
  },
  fonts: { display: "Montserrat ExtraBold", text: "Inter Medium" },
  safe_area: { left: 96, top: 54, right: 1824, bottom: 1026 },
  caption_zone: { top: 878, bottom: 1018 },
};

function Nothing() {
  return null;
}

// A callout's own brief, so that Remotion Studio can open the composition (CMO-001).
const placeholderCallout = {
  kind: "emphasis",
  placement: "presenter",
  frame_height: 1080,
  exit_frame: 60,
  parts: [{ id: "p1", text: "Placeholder", role: "accent", colour: "#4DA3FF", frame: 6 }],
  theme: {
    surface: "#161C28",
    text: "#FFFFFF",
    muted: "#9AA4B2",
    accent: "#4DA3FF",
    positive: "#2ED573",
    negative: "#FF4D4D",
    number: "#FFB000",
  },
  fonts: { display: "Montserrat ExtraBold", text: "Inter Medium" },
  look: {},
};

const defaults = (engine: string): GraphicInput => ({
  engine,
  width: 1920,
  height: 1080,
  fps: 24,
  frames: 72,
  resolved: placeholder,
  input: null,
  code: null,
});

// The compositions of §4.6. The test card (GFX-005), the templates (GFX-007), the blocks
// (GFX-009), the generated component (GFX-010) and the callout (CMO-001) are drawn. `BlocksLayout` draws nothing: it
// only measures a block scene for `POST /layout`.
export function Root() {
  return (
    <>
      <Composition
        id="TestCard"
        component={TestCard}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={defaults("test_card")}
        calculateMetadata={metadata}
      />
      <Composition
        id="Templates"
        component={Templates}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={defaults("remotion_templates")}
        calculateMetadata={metadata}
      />
      <Composition
        id="Blocks"
        component={Blocks}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={defaults("remotion_blocks")}
        calculateMetadata={metadata}
      />
      <Composition
        id="BlocksLayout"
        component={Nothing}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={{ ...defaults("remotion_blocks"), at_frames: [], report: null }}
        calculateMetadata={layoutMetadata}
      />
      <Composition
        id="Generated"
        component={Generated}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={defaults("generated_component")}
        calculateMetadata={metadata}
      />
      <Composition
        id="Callout"
        component={Callout}
        width={768}
        height={346}
        fps={24}
        durationInFrames={72}
        defaultProps={{
          ...defaults("callout_component"),
          width: 768,
          height: 346,
          resolved: placeholderCallout as unknown as Resolved,
        }}
        calculateMetadata={metadata}
      />
    </>
  );
}
