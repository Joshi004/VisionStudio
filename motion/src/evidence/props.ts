import type { Box, ImagePayload } from "../shared/camera";
import type { GraphicInput } from "../types";

// A box of the screenshot's world, `[x, y, width, height]` in the screenshot's own pixels: the image
// is `[0, 0, image_w, image_h]` (see `backend/app/services/evidence_clip_layout.py`).
export type { Box };

export type EvidenceImage = ImagePayload;

// What the backend sends as `resolved` for an evidence clip (EVD-008). The camera, the stage and
// the timeline are decided there; the composition only draws them.
export type EvidenceResolved = {
  accent: string;
  background: string;
  fonts: { display: string; text: string };
  safe_area: { left: number; top: number; right: number; bottom: number };
  caption_zone: { top: number; bottom: number };
  // Where the screenshot sits in the world, and where the context image's crop sits (or null when
  // the screenshot alone covers every frame).
  image_box: Box;
  context_box: Box | null;
  // The camera at the first frame and after the zoom.
  start: Box;
  end: Box;
  // The quote's lines in the world.
  rects: Box[];
  timeline: { zoom_start: number; zoom_end: number; sweep_start: number; sweep_end: number };
  badge_box: Box;
  badge: { publisher: string; date: string | null; page: number | null };
  // Only for an evidence card (EVD-011): the clip is a transparent canvas the size of the card, with a
  // rounded panel that fills it, and it fades in and out over `fade_frames` at each end. Without it
  // the clip is a full-frame evidence shot on `background`.
  card: { radius: number; fade_frames: number } | null;
  // Only for a split evidence shot (EVD-016): the picture, the badge and the highlight are drawn in
  // the evidence panel `[x, y, width, height]` of the frame, in the panel's own pixels, and the rest
  // of the frame (the callout panel) is the background. `edge` is the side of the evidence panel that
  // touches the callout panel, where a line is drawn.
  panel: { x: number; y: number; width: number; height: number; edge: "top" | "right" } | null;
};

export type EvidenceInput = { image: EvidenceImage; context: EvidenceImage | null };

export type Evidence = { resolved: EvidenceResolved; input: EvidenceInput };

const COLOUR = /^#[0-9a-fA-F]{6}$/;

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`The evidence clip's ${what} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string" || value === "") {
    throw new Error(`The evidence clip's ${what} must be a non-empty string.`);
  }
  return value;
}

function colour(value: unknown, what: string): string {
  if (typeof value !== "string" || !COLOUR.test(value)) {
    throw new Error(`The evidence clip's ${what} must be a #RRGGBB colour.`);
  }
  return value;
}

function whole(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`The evidence clip's ${what} must be a whole number.`);
  }
  return value;
}

function box(value: unknown, what: string): Box {
  if (
    !Array.isArray(value) ||
    value.length !== 4 ||
    !value.every((n) => typeof n === "number" && Number.isFinite(n))
  ) {
    throw new Error(`The evidence clip's ${what} must be [x, y, width, height].`);
  }
  const [x, y, w, h] = value as number[];
  if (w! <= 0 || h! <= 0) throw new Error(`The evidence clip's ${what} has no size.`);
  return [x!, y!, w!, h!];
}

function image(value: unknown, what: string): EvidenceImage {
  const raw = record(value, what);
  const mime = raw["mime"];
  if (mime !== "image/png" && mime !== "image/jpeg") {
    throw new Error(`The evidence clip's ${what} must be a PNG or a JPEG.`);
  }
  return { mime, base64: text(raw["base64"], `${what} data`) };
}

// Reads and checks a render's `resolved` and `input`. Every problem is a readable error, which
// fails the render before any frame is drawn.
export function readEvidence(props: GraphicInput): Evidence {
  const raw = record(props.resolved, "resolved brief");

  const fontsRaw = record(raw["fonts"], "fonts");
  const safe = record(raw["safe_area"], "safe_area");
  const caption = record(raw["caption_zone"], "caption_zone");
  const line = record(raw["timeline"], "timeline");
  const badge = record(raw["badge"], "badge");

  if (!Array.isArray(raw["rects"]) || raw["rects"].length === 0) {
    throw new Error("The evidence clip has no quote to highlight.");
  }

  const timeline = {
    zoom_start: whole(line["zoom_start"], "timeline.zoom_start"),
    zoom_end: whole(line["zoom_end"], "timeline.zoom_end"),
    sweep_start: whole(line["sweep_start"], "timeline.sweep_start"),
    sweep_end: whole(line["sweep_end"], "timeline.sweep_end"),
  };
  if (
    timeline.zoom_start < 0 ||
    timeline.zoom_end <= timeline.zoom_start ||
    timeline.sweep_start < timeline.zoom_end ||
    timeline.sweep_end <= timeline.sweep_start ||
    timeline.sweep_end >= props.frames
  ) {
    throw new Error("The evidence clip's timeline does not fit its length.");
  }

  const pageRaw = badge["page"];
  const dateRaw = badge["date"];
  const input = record(props.input, "input");

  let card: EvidenceResolved["card"] = null;
  if (raw["card"] !== undefined && raw["card"] !== null) {
    const cardRaw = record(raw["card"], "card");
    const radius = Number(cardRaw["radius"]);
    const fade = whole(cardRaw["fade_frames"], "card.fade_frames");
    if (!Number.isFinite(radius) || radius < 0) throw new Error("The evidence card's radius must be 0 or more.");
    if (fade < 0 || fade * 2 >= props.frames) throw new Error("The evidence card's fades do not fit its length.");
    card = { radius, fade_frames: fade };
  }

  let panel: EvidenceResolved["panel"] = null;
  if (raw["panel"] !== undefined && raw["panel"] !== null) {
    const panelRaw = record(raw["panel"], "panel");
    const x = whole(panelRaw["x"], "panel.x");
    const y = whole(panelRaw["y"], "panel.y");
    const panelWidth = whole(panelRaw["width"], "panel.width");
    const panelHeight = whole(panelRaw["height"], "panel.height");
    const edge = panelRaw["edge"];
    if (edge !== "top" && edge !== "right") throw new Error("The evidence panel's edge must be top or right.");
    if (
      x < 0 ||
      y < 0 ||
      panelWidth < 2 ||
      panelHeight < 2 ||
      x + panelWidth > props.width ||
      y + panelHeight > props.height
    ) {
      throw new Error("The evidence panel does not fit the frame.");
    }
    if (card !== null) throw new Error("An evidence card cannot be split.");
    panel = { x, y, width: panelWidth, height: panelHeight, edge };
  }

  const resolved: EvidenceResolved = {
    accent: colour(raw["accent"], "accent"),
    background: colour(raw["background"], "background"),
    fonts: { display: text(fontsRaw["display"], "fonts.display"), text: text(fontsRaw["text"], "fonts.text") },
    safe_area: {
      left: Number(safe["left"]),
      top: Number(safe["top"]),
      right: Number(safe["right"]),
      bottom: Number(safe["bottom"]),
    },
    caption_zone: { top: Number(caption["top"]), bottom: Number(caption["bottom"]) },
    image_box: box(raw["image_box"], "image_box"),
    context_box: raw["context_box"] === null || raw["context_box"] === undefined ? null : box(raw["context_box"], "context_box"),
    start: box(raw["start"], "start camera"),
    end: box(raw["end"], "end camera"),
    rects: (raw["rects"] as unknown[]).map((entry, index) => box(entry, `rect ${index + 1}`)),
    timeline,
    badge_box: box(raw["badge_box"], "badge_box"),
    badge: {
      publisher: text(badge["publisher"], "badge.publisher"),
      date: typeof dateRaw === "string" && dateRaw !== "" ? dateRaw : null,
      page: typeof pageRaw === "number" && Number.isInteger(pageRaw) ? pageRaw : null,
    },
    card,
    panel,
  };

  const contextRaw = input["context"];
  const evidenceInput: EvidenceInput = {
    image: image(input["image"], "image"),
    context: contextRaw === null || contextRaw === undefined ? null : image(contextRaw, "context image"),
  };
  if ((resolved.context_box === null) !== (evidenceInput.context === null)) {
    throw new Error("The context image and its box must come together.");
  }
  return { resolved, input: evidenceInput };
}
