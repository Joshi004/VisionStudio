import type { GraphicInput } from "../types";

// A box of the frame, `[x, y, width, height]` in output pixels.
export type Box = [number, number, number, number];

// What the backend sends as `resolved` for a sound bite overlay (SB-009): a transparent, full-frame
// clip laid over a real person's clip. The places and the times are decided in
// `backend/app/services/soundbite_render.py`; the composition only draws them.
export type SoundbiteResolved = {
  accent: string;
  fonts: { display: string; text: string };
  // The lower third: the speaker, then the role, venue and month. Null when the clip has none (no
  // name, or too short for it).
  lower_third: {
    box: Box;
    name: string;
    detail: string;
    start_frame: number;
    end_frame: number;
    fade_frames: number;
  } | null;
  // The source credit, small, for the whole clip. Null when the channel is not known.
  credit: { text: string; box: Box } | null;
};

const COLOUR = /^#[0-9a-fA-F]{6}$/;

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`The sound bite overlay's ${what} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string" || value === "") {
    throw new Error(`The sound bite overlay's ${what} must be a non-empty string.`);
  }
  return value;
}

function whole(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`The sound bite overlay's ${what} must be a whole number.`);
  }
  return value;
}

function box(value: unknown, what: string): Box {
  if (
    !Array.isArray(value) ||
    value.length !== 4 ||
    !value.every((n) => typeof n === "number" && Number.isFinite(n))
  ) {
    throw new Error(`The sound bite overlay's ${what} must be [x, y, width, height].`);
  }
  const [x, y, w, h] = value as number[];
  if (w! <= 0 || h! <= 0) throw new Error(`The sound bite overlay's ${what} has no size.`);
  return [x!, y!, w!, h!];
}

// Reads and checks a render's `resolved`. Every problem is a readable error, which fails the render
// before any frame is drawn.
export function readSoundbite(props: GraphicInput): SoundbiteResolved {
  const raw = record(props.resolved, "resolved brief");
  const fonts = record(raw["fonts"], "fonts");
  const accent = raw["accent"];
  if (typeof accent !== "string" || !COLOUR.test(accent)) {
    throw new Error("The sound bite overlay's accent must be a #RRGGBB colour.");
  }

  let lowerThird: SoundbiteResolved["lower_third"] = null;
  if (raw["lower_third"] !== undefined && raw["lower_third"] !== null) {
    const third = record(raw["lower_third"], "lower_third");
    const start = whole(third["start_frame"], "lower_third.start_frame");
    const end = whole(third["end_frame"], "lower_third.end_frame");
    const fade = whole(third["fade_frames"], "lower_third.fade_frames");
    if (start < 0 || end <= start || end > props.frames || fade < 0 || fade * 2 > end - start) {
      throw new Error("The sound bite overlay's lower third does not fit its length.");
    }
    const detail = third["detail"];
    lowerThird = {
      box: box(third["box"], "lower_third.box"),
      name: text(third["name"], "lower_third.name"),
      detail: typeof detail === "string" ? detail : "",
      start_frame: start,
      end_frame: end,
      fade_frames: fade,
    };
  }

  let credit: SoundbiteResolved["credit"] = null;
  if (raw["credit"] !== undefined && raw["credit"] !== null) {
    credit = { text: text(raw["credit"], "credit"), box: box(raw["credit_box"], "credit_box") };
  }

  return {
    accent,
    fonts: { display: text(fonts["display"], "fonts.display"), text: text(fonts["text"], "fonts.text") },
    lower_third: lowerThird,
    credit,
  };
}
