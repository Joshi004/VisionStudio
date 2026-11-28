import type { Box, ImagePayload } from "../shared/camera";
import type { GraphicInput } from "../types";

// What the backend sends as `resolved` for a footage clip (FTG-005,
// `backend/app/services/footage_clip_layout.py`). Every box and camera is decided there; the
// composition only draws them.
export type FootageMode = "image" | "page" | "pdf";

export type FootageResolved = {
  mode: FootageMode;
  accent: string;
  background: string;
  fonts: { display: string; text: string };
  // A photo: the picture and the blurred copy behind it (null when the picture fills the frame), in
  // output pixels at the first frame, and the zoom of the whole frame at the last frame.
  image: { picture: Box; backdrop: Box | null; zoom_end: number } | null;
  blur_sigma: number;
  // The brightness of the blurred copy, 1 being unchanged.
  darken: number;
  // A page or a PDF: the part of the frame the world is drawn in, the camera at the first frame and
  // after the move, the focus lines in the world, and the frames of the move and of the highlight.
  view: Box | null;
  start: Box | null;
  end: Box | null;
  image_px: [number, number];
  rects: Box[];
  timeline: { zoom_start: number; zoom_end: number; sweep_start: number | null; sweep_end: number | null } | null;
  // A page: the browser window it is drawn in.
  window: { box: Box; bar_height: number; radius: number; address: string } | null;
};

export type Footage = { resolved: FootageResolved; image: ImagePayload };

const COLOUR = /^#[0-9a-fA-F]{6}$/;

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`The footage clip's ${what} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string" || value === "") {
    throw new Error(`The footage clip's ${what} must be a non-empty string.`);
  }
  return value;
}

function colour(value: unknown, what: string): string {
  if (typeof value !== "string" || !COLOUR.test(value)) {
    throw new Error(`The footage clip's ${what} must be a #RRGGBB colour.`);
  }
  return value;
}

function finite(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`The footage clip's ${what} must be a number.`);
  }
  return value;
}

function whole(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`The footage clip's ${what} must be a whole number.`);
  }
  return value;
}

function box(value: unknown, what: string): Box {
  if (
    !Array.isArray(value) ||
    value.length !== 4 ||
    !value.every((n) => typeof n === "number" && Number.isFinite(n))
  ) {
    throw new Error(`The footage clip's ${what} must be [x, y, width, height].`);
  }
  const [x, y, w, h] = value as number[];
  if (w! <= 0 || h! <= 0) throw new Error(`The footage clip's ${what} has no size.`);
  return [x!, y!, w!, h!];
}

function payload(value: unknown): ImagePayload {
  const raw = record(value, "image");
  const mime = raw["mime"];
  if (mime !== "image/png" && mime !== "image/jpeg") {
    throw new Error("The footage clip's image must be a PNG or a JPEG.");
  }
  return { mime, base64: text(raw["base64"], "image data") };
}

// Reads and checks a render's `resolved` and `input`. Every problem is a readable error, which
// fails the render before any frame is drawn.
export function readFootage(props: GraphicInput): Footage {
  const raw = record(props.resolved, "resolved brief");
  const input = record(props.input, "input");
  const fonts = record(raw["fonts"], "fonts");
  const mode = raw["mode"];
  if (mode !== "image" && mode !== "page" && mode !== "pdf") {
    throw new Error("The footage clip's mode must be image, page or pdf.");
  }
  const sizeRaw = raw["image_px"];
  if (!Array.isArray(sizeRaw) || sizeRaw.length !== 2) {
    throw new Error("The footage clip's image_px must be [width, height].");
  }

  const resolved: FootageResolved = {
    mode,
    accent: colour(raw["accent"], "accent"),
    background: colour(raw["background"], "background"),
    fonts: { display: text(fonts["display"], "fonts.display"), text: text(fonts["text"], "fonts.text") },
    image: null,
    blur_sigma: finite(raw["blur_sigma"], "blur_sigma"),
    darken: finite(raw["darken"], "darken"),
    view: null,
    start: null,
    end: null,
    image_px: [finite(sizeRaw[0], "image_px"), finite(sizeRaw[1], "image_px")],
    rects: [],
    timeline: null,
    window: null,
  };
  if (resolved.image_px[0] <= 0 || resolved.image_px[1] <= 0) {
    throw new Error("The footage clip's image has no size.");
  }

  if (mode === "image") {
    const imageRaw = record(raw["image"], "image look");
    const zoomEnd = finite(imageRaw["zoom_end"], "image.zoom_end");
    if (zoomEnd < 1) throw new Error("The footage clip's image zoom must be 1 or more.");
    const backdrop = imageRaw["backdrop"];
    resolved.image = {
      picture: box(imageRaw["picture"], "picture"),
      backdrop: backdrop === null || backdrop === undefined ? null : box(backdrop, "backdrop"),
      zoom_end: zoomEnd,
    };
    return { resolved, image: payload(input["image"]) };
  }

  const line = record(raw["timeline"], "timeline");
  const sweepStart = line["sweep_start"];
  const sweepEnd = line["sweep_end"];
  const focused = sweepStart !== null && sweepStart !== undefined;
  const timeline = {
    zoom_start: whole(line["zoom_start"], "timeline.zoom_start"),
    zoom_end: whole(line["zoom_end"], "timeline.zoom_end"),
    sweep_start: focused ? whole(sweepStart, "timeline.sweep_start") : null,
    sweep_end: focused ? whole(sweepEnd, "timeline.sweep_end") : null,
  };
  if (timeline.zoom_start < 0 || timeline.zoom_end <= timeline.zoom_start || timeline.zoom_end > props.frames) {
    throw new Error("The footage clip's camera move does not fit its length.");
  }
  if (
    timeline.sweep_start !== null &&
    timeline.sweep_end !== null &&
    (timeline.sweep_start < timeline.zoom_end ||
      timeline.sweep_end <= timeline.sweep_start ||
      timeline.sweep_end >= props.frames)
  ) {
    throw new Error("The footage clip's highlight does not fit its length.");
  }
  const rects = Array.isArray(raw["rects"]) ? (raw["rects"] as unknown[]) : [];
  if (focused !== (rects.length > 0)) {
    throw new Error("The footage clip's focus lines and its highlight must come together.");
  }
  resolved.view = box(raw["view"], "view");
  resolved.start = box(raw["start"], "start camera");
  resolved.end = box(raw["end"], "end camera");
  resolved.rects = rects.map((entry, index) => box(entry, `focus line ${index + 1}`));
  resolved.timeline = timeline;

  if (mode === "page") {
    const windowRaw = record(raw["window"], "window");
    const bar = whole(windowRaw["bar_height"], "window.bar_height");
    const windowBox = box(windowRaw["box"], "window.box");
    if (bar < 1 || bar >= windowBox[3]) throw new Error("The footage clip's title bar does not fit its window.");
    resolved.window = {
      box: windowBox,
      bar_height: bar,
      radius: finite(windowRaw["radius"], "window.radius"),
      address: typeof windowRaw["address"] === "string" ? windowRaw["address"] : "",
    };
    // The world is drawn in the window's page area, which is what `view` says it is.
    const [, , viewW, viewH] = resolved.view;
    if (Math.abs(viewW - windowBox[2]) > 1 || Math.abs(viewH - (windowBox[3] - bar)) > 1) {
      throw new Error("The footage clip's view is not its window's page area.");
    }
  }
  return { resolved, image: payload(input["image"]) };
}
