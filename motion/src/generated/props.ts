import type { Box, GraphicInput, Zone } from "../types";

// The props of a generated component (§4.5.3 of Graphics_lab_implementation_phases.md). Derived
// values are merged into `facts`, so a component finds every number by one id.
export type GraphicProps = {
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  theme: {
    background: string;
    surface: string;
    text: string;
    muted: string;
    accent: string;
    positive: string;
    negative: string;
    number: string;
    fontDisplay: string;
    fontText: string;
  };
  facts: Record<string, { label: string; value: number; display: string }>;
  beats: Record<string, { frame: number; shows: string }>;
  safeArea: Box;
  captionZone: Zone;
};

export function graphicProps(input: GraphicInput): GraphicProps {
  const { resolved } = input;
  const facts: GraphicProps["facts"] = {};
  for (const [id, measure] of Object.entries({ ...resolved.facts, ...resolved.derived })) {
    facts[id] = { label: measure.label, value: measure.value, display: measure.display };
  }
  const beats: GraphicProps["beats"] = {};
  for (const [id, beat] of Object.entries(resolved.beats)) {
    beats[id] = { frame: beat.frame, shows: beat.shows };
  }
  const { theme } = resolved;
  return {
    width: input.width,
    height: input.height,
    fps: input.fps,
    durationInFrames: input.frames,
    theme: {
      background: theme.background,
      surface: theme.surface,
      text: theme.text,
      muted: theme.muted,
      accent: theme.accent,
      positive: theme.positive,
      negative: theme.negative,
      number: theme.number,
      fontDisplay: resolved.fonts.display,
      fontText: resolved.fonts.text,
    },
    facts,
    beats,
    safeArea: { ...resolved.safe_area },
    captionZone: { ...resolved.caption_zone },
  };
}
