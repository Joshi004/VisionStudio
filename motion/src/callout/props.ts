import type { GraphicInput } from "../types";

export const CALLOUT_KINDS = ["emphasis", "number", "question", "comparison", "list", "section_title"] as const;
export const CALLOUT_PLACEMENTS = ["presenter", "broll", "portrait", "title"] as const;

export type CalloutKind = (typeof CALLOUT_KINDS)[number];
export type CalloutPlacement = (typeof CALLOUT_PLACEMENTS)[number];

// One text of the callout, in order: the text of an emphasis, number, question or section title,
// or each item of a list, or each side of a comparison.
export type CalloutPart = { id: string; text: string; role: string; colour: string; frame: number };

export type CalloutTheme = {
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

// The props of a generated callout component (§4.4.1). There is no `theme.background`: the canvas
// is transparent.
export type CalloutProps = {
  // The zone's size in pixels (the whole canvas) and the callout's length.
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  // The output frame's height, for text size rules.
  frameHeight: number;
  kind: CalloutKind;
  placement: CalloutPlacement;
  parts: CalloutPart[];
  theme: CalloutTheme;
  look: Record<string, string>;
  // From this frame on, the composition fades everything out; nothing new may start after it.
  exitFrame: number;
};

// What the backend sends as `resolved` for a callout render (CMO-003 builds it).
export type CalloutResolved = {
  kind: CalloutKind;
  placement: CalloutPlacement;
  frame_height: number;
  // The block scenes of CMO-004 need these two; a component does not read them.
  frame_width?: number;
  motion?: string;
  exit_frame: number;
  parts: CalloutPart[];
  theme: Omit<CalloutTheme, "fontDisplay" | "fontText">;
  fonts: { display: string; text: string };
  look: Record<string, string>;
  // Preview only: a colour painted under the callout so that an H.264 file can show it.
  backdrop?: string;
};

const MOTIONS = ["snappy", "smooth", "calm"];

const THEME_KEYS = ["surface", "text", "muted", "accent", "positive", "negative", "number"] as const;

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`The callout's ${what} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string" || value === "") throw new Error(`The callout's ${what} must be a non-empty string.`);
  return value;
}

function whole(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) throw new Error(`The callout's ${what} must be a whole number.`);
  return value;
}

// Reads and checks `input.resolved` of a callout render. Every problem is a readable error, which
// fails the render before any frame is drawn.
export function readCallout(input: GraphicInput): CalloutResolved {
  const raw = record(input.resolved, "resolved brief");

  const kind = raw["kind"];
  if (!CALLOUT_KINDS.includes(kind as CalloutKind)) throw new Error(`Unknown callout kind: ${String(kind)}.`);
  const placement = raw["placement"];
  if (!CALLOUT_PLACEMENTS.includes(placement as CalloutPlacement)) {
    throw new Error(`Unknown callout placement: ${String(placement)}.`);
  }

  const frameHeight = whole(raw["frame_height"], "frame_height");
  const frameWidthRaw = raw["frame_width"];
  const frameWidth = frameWidthRaw === undefined ? undefined : whole(frameWidthRaw, "frame_width");
  const motionRaw = raw["motion"];
  if (motionRaw !== undefined && !(typeof motionRaw === "string" && MOTIONS.includes(motionRaw))) {
    throw new Error(`The callout's motion must be one of ${MOTIONS.join(", ")}.`);
  }
  const exitFrame = whole(raw["exit_frame"], "exit_frame");
  if (exitFrame <= 0 || exitFrame >= input.frames) {
    throw new Error(`The callout's exit_frame (${exitFrame}) must be after the first frame and before the last (${input.frames}).`);
  }

  if (!Array.isArray(raw["parts"]) || raw["parts"].length === 0) throw new Error("The callout has no parts.");
  const ids = new Set<string>();
  const parts = (raw["parts"] as unknown[]).map((item, index): CalloutPart => {
    const part = record(item, `part ${index + 1}`);
    const id = text(part["id"], `part ${index + 1} id`);
    if (ids.has(id)) throw new Error(`Two parts have the id "${id}".`);
    ids.add(id);
    const frame = whole(part["frame"], `part "${id}" frame`);
    if (frame < 0 || frame >= exitFrame) {
      throw new Error(`The frame of part "${id}" (${frame}) must be from 0 up to the exit frame (${exitFrame}).`);
    }
    return {
      id,
      text: text(part["text"], `part "${id}" text`),
      role: text(part["role"], `part "${id}" role`),
      colour: text(part["colour"], `part "${id}" colour`),
      frame,
    };
  });

  const themeRaw = record(raw["theme"], "theme");
  const theme = {} as Record<string, string>;
  for (const key of THEME_KEYS) theme[key] = text(themeRaw[key], `theme.${key}`);

  const fontsRaw = record(raw["fonts"], "fonts");

  const lookRaw = record(raw["look"], "look");
  const look: Record<string, string> = {};
  for (const [key, value] of Object.entries(lookRaw)) look[key] = String(value);

  const backdrop = raw["backdrop"];
  if (backdrop !== undefined && !(typeof backdrop === "string" && /^#[0-9a-fA-F]{6}$/.test(backdrop))) {
    throw new Error("The callout's backdrop must be a #RRGGBB colour.");
  }

  return {
    kind: kind as CalloutKind,
    placement: placement as CalloutPlacement,
    frame_height: frameHeight,
    ...(frameWidth === undefined ? {} : { frame_width: frameWidth }),
    ...(motionRaw === undefined ? {} : { motion: motionRaw as string }),
    exit_frame: exitFrame,
    parts,
    theme: theme as CalloutResolved["theme"],
    fonts: { display: text(fontsRaw["display"], "fonts.display"), text: text(fontsRaw["text"], "fonts.text") },
    look,
    ...(backdrop === undefined ? {} : { backdrop }),
  };
}

export function calloutProps(input: GraphicInput, callout: CalloutResolved): CalloutProps {
  return {
    width: input.width,
    height: input.height,
    fps: input.fps,
    durationInFrames: input.frames,
    frameHeight: callout.frame_height,
    kind: callout.kind,
    placement: callout.placement,
    parts: callout.parts.map((part) => ({ ...part })),
    theme: {
      ...callout.theme,
      fontDisplay: callout.fonts.display,
      fontText: callout.fonts.text,
    },
    look: { ...callout.look },
    exitFrame: callout.exit_frame,
  };
}
