import { Composition } from "remotion";
import type { CalculateMetadataFunction } from "remotion";

import "./fonts";
import { NotBuiltYet } from "./NotBuiltYet";
import { TestCard } from "./TestCard";
import type { GraphicInput, Resolved } from "./types";

// The size, frame rate and length of every video come from the input, so the frame count is
// exactly the one the backend asked for.
const metadata: CalculateMetadataFunction<GraphicInput> = ({ props }) => ({
  width: props.width,
  height: props.height,
  fps: props.fps,
  durationInFrames: props.frames,
});

const placeholder: Resolved = {
  width: 1920,
  height: 1080,
  fps: 24,
  frames: 72,
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

// The four compositions of §4.6. Only the test card is drawn in GFX-005; the other three show
// "not built yet" and are filled in by GFX-007, GFX-009 and GFX-010.
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
        component={NotBuiltYet}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={defaults("remotion_templates")}
        calculateMetadata={metadata}
      />
      <Composition
        id="Blocks"
        component={NotBuiltYet}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={defaults("remotion_blocks")}
        calculateMetadata={metadata}
      />
      <Composition
        id="Generated"
        component={NotBuiltYet}
        width={1920}
        height={1080}
        fps={24}
        durationInFrames={72}
        defaultProps={defaults("generated_component")}
        calculateMetadata={metadata}
      />
    </>
  );
}
