// The shapes the backend sends with a render (§4.4 and §4.6 of Graphics_lab_implementation_phases.md).
// Only what the compositions read is typed here; the rest of the resolved brief passes through.

export type Theme = {
  background: string;
  surface: string;
  text: string;
  muted: string;
  accent: string;
  positive: string;
  negative: string;
  number: string;
  background_style: string;
  motion: string;
};

export type Box = { left: number; top: number; right: number; bottom: number };
export type Zone = { top: number; bottom: number };

// A fact or a derived value of the resolved brief: its full value and the text code wrote for it.
export type Measure = { label: string; value: number; unit: string; display: string };

export type Resolved = {
  width: number;
  height: number;
  fps: number;
  frames: number;
  facts: Record<string, Measure>;
  derived: Record<string, Measure>;
  beats: Record<string, { frame: number; shows: string }>;
  theme: Theme;
  fonts: { display: string; text: string };
  safe_area: Box;
  caption_zone: Zone;
  [key: string]: unknown;
};

// The props of every composition. `width`, `height`, `fps` and `frames` are also the size and the
// exact length of the video (see `calculateMetadata` in Root.tsx).
export type GraphicInput = {
  engine: string;
  width: number;
  height: number;
  fps: number;
  frames: number;
  resolved: Resolved;
  input: unknown;
  code: string | null;
};
