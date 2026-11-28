// The JSON schema of POST /renders. Fastify checks the body against it before any handler runs,
// so a malformed request never reaches Remotion.

export const ENGINES = [
  "test_card",
  "remotion_templates",
  "remotion_blocks",
  "generated_component",
  "callout_component",
  "callout_blocks",
  // An evidence clip (EVD-008): a screenshot zoomed to a quote. Its images travel in the request,
  // so it is asked for on POST /evidence-renders only, never on POST /renders.
  "evidence_clip",
  // A footage clip (FTG-005): a photo, a web page or a PDF page. Its picture travels in the request
  // like an evidence clip's, so it is asked for on POST /evidence-renders only.
  "footage_clip",
  // The lower third and the source credit laid over a sound bite clip (SB-009): a transparent
  // full-frame clip, always ProRes 4444 like a callout, with no images in its request.
  "soundbite_overlay",
] as const;
export type Engine = (typeof ENGINES)[number];

export const EVIDENCE_ENGINE: Engine = "evidence_clip";
export const FOOTAGE_ENGINE: Engine = "footage_clip";
export const SOUNDBITE_ENGINE: Engine = "soundbite_overlay";
// A sound bite is at most 15 s long (SB-007): 1800 frames is 60 s at 30 fps, as for a callout.
const SOUNDBITE_MAX_FRAMES = 1800;
// The body of POST /evidence-renders: a screenshot and a context image as base64, so far more than
// the 1 MB of the other routes. The backend refuses to send more than 30 MB.
export const EVIDENCE_BODY_LIMIT_BYTES = 32 * 1024 * 1024;
const EVIDENCE_IMAGE_BASE64_MAX = 28 * 1024 * 1024;

// The engines that draw a callout (CMO-001): a transparent clip laid over a shot. Only they may be
// asked for ProRes 4444, and they are held to CALLOUT_MAX_FRAMES. `callout_blocks` (CMO-004)
// draws the block scene of a callout.
export const CALLOUT_ENGINES: readonly Engine[] = ["callout_component", "callout_blocks"];

export function isCalloutEngine(engine: Engine): boolean {
  return CALLOUT_ENGINES.includes(engine);
}

// 180 s at 24 fps: the longest Graphics lab graphic.
export const MAX_FRAMES = 4320;
// A callout stays up as long as its narration unit, up to 60 s: 1800 frames is 60 s at 30 fps.
export const CALLOUT_MAX_FRAMES = 1800;
export const MAX_TIME_LIMIT_S = 900;

// H.264 for every engine; ProRes 4444 with an alpha channel for the callout engines only.
export type Encoding = {
  codec: "h264" | "prores";
  // H.264 only.
  crf?: number;
  preset?: string;
  color_space?: "bt709";
  // ProRes only.
  prores_profile?: "4444";
  pixel_format: "yuv420p" | "yuva444p10le";
};

export type RenderRequest = {
  engine: Engine;
  width: number;
  height: number;
  fps: number;
  frames: number;
  resolved: Record<string, unknown>;
  input: unknown;
  code?: string | null;
  encoding: Encoding;
  time_limit_s: number;
};

export const renderRequestSchema = {
  type: "object",
  additionalProperties: false,
  required: ["engine", "width", "height", "fps", "frames", "resolved", "encoding", "time_limit_s"],
  properties: {
    engine: { type: "string", enum: [...ENGINES] },
    // yuv420p needs even sizes.
    width: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    height: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    fps: { type: "integer", minimum: 1, maximum: 60 },
    // The most any engine may ask for; `requestProblem` holds the callout engines to
    // CALLOUT_MAX_FRAMES.
    frames: { type: "integer", minimum: 1, maximum: MAX_FRAMES },
    resolved: { type: "object" },
    input: {},
    code: { type: ["string", "null"], maxLength: 100_000 },
    // One object for both codecs (a `oneOf` would let the validator strip fields while it tries
    // the branches); `requestProblem` says which fields each codec needs.
    encoding: {
      type: "object",
      additionalProperties: false,
      required: ["codec", "pixel_format"],
      properties: {
        codec: { type: "string", enum: ["h264", "prores"] },
        crf: { type: "integer", minimum: 0, maximum: 51 },
        preset: {
          type: "string",
          enum: [
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
          ],
        },
        color_space: { type: "string", enum: ["bt709"] },
        prores_profile: { type: "string", enum: ["4444"] },
        pixel_format: { type: "string", enum: ["yuv420p", "yuva444p10le"] },
      },
    },
    time_limit_s: { type: "integer", minimum: 10, maximum: MAX_TIME_LIMIT_S },
  },
} as const;

const evidenceImageSchema = {
  type: "object",
  additionalProperties: false,
  required: ["mime", "base64"],
  properties: {
    mime: { type: "string", enum: ["image/png", "image/jpeg"] },
    base64: { type: "string", minLength: 4, maxLength: EVIDENCE_IMAGE_BASE64_MAX },
  },
} as const;

// The body of POST /evidence-renders (EVD-008, FTG-005): a render request of the engine
// `evidence_clip` or `footage_clip`, whose `input` is `{image, context}`. The screenshot is always there; the context image only when
// the camera goes past the screenshot's edge.
export const evidenceRenderRequestSchema = {
  ...renderRequestSchema,
  required: [...renderRequestSchema.required, "input"],
  properties: {
    ...renderRequestSchema.properties,
    engine: { type: "string", enum: [EVIDENCE_ENGINE, FOOTAGE_ENGINE] },
    input: {
      type: "object",
      additionalProperties: false,
      required: ["image"],
      properties: {
        image: evidenceImageSchema,
        context: { anyOf: [evidenceImageSchema, { type: "null" }] },
      },
    },
  },
} as const;

// The body of POST /layout (GFX-009): the size, length and resolved brief of a render, the block
// scene as its `input`, and the frames at which to report the texts on the screen.
export type LayoutRequest = {
  // `callout` (CMO-004): the scene is a callout's, `resolved` is the callout's brief and `frames`
  // may be as long as a callout. Without it: a graphic shot's scene.
  mode?: "blocks" | "callout";
  width: number;
  height: number;
  fps: number;
  frames: number;
  resolved: Record<string, unknown>;
  input: unknown;
  at_frames: number[];
};

export const MAX_LAYOUT_FRAMES = 32;

export const layoutRequestSchema = {
  type: "object",
  additionalProperties: false,
  required: ["width", "height", "fps", "frames", "resolved", "input", "at_frames"],
  properties: {
    mode: { type: "string", enum: ["blocks", "callout"] },
    width: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    height: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    fps: { type: "integer", minimum: 1, maximum: 60 },
    // The most any mode may ask for; `layoutProblem` holds a callout's scene to CALLOUT_MAX_FRAMES.
    frames: { type: "integer", minimum: 1, maximum: MAX_FRAMES },
    resolved: { type: "object" },
    input: {},
    at_frames: {
      type: "array",
      minItems: 1,
      maxItems: MAX_LAYOUT_FRAMES,
      items: { type: "integer", minimum: 0, maximum: MAX_FRAMES - 1 },
    },
  },
} as const;

// The rules of a layout request that the JSON schema cannot hold. A readable message, or null.
export function layoutProblem(request: LayoutRequest): string | null {
  if (request.mode === "callout") {
    if (request.frames > CALLOUT_MAX_FRAMES) {
      return `A callout scene is laid out at most ${CALLOUT_MAX_FRAMES} frames long.`;
    }
    if (request.at_frames.some((frame) => frame >= CALLOUT_MAX_FRAMES)) {
      return `A callout scene is measured at frames below ${CALLOUT_MAX_FRAMES}.`;
    }
    return null;
  }
  if (request.frames > MAX_FRAMES) return `A block scene is laid out at most ${MAX_FRAMES} frames long.`;
  if (request.at_frames.some((frame) => frame >= MAX_FRAMES)) {
    return `A block scene is measured at frames below ${MAX_FRAMES}.`;
  }
  return null;
}

export const idParamsSchema = {
  type: "object",
  required: ["id"],
  properties: {
    id: {
      type: "string",
      pattern: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    },
  },
} as const;

// The body of POST /checks (GFX-010): the size, length and resolved brief of a render, and the
// component's code. The backend's static checks hold the same limit of characters.
export const MAX_CODE_CHARS = 40_000;
// The most frames one check may draw when the request names them (EXG-006).
export const MAX_CHECK_FRAMES = 16;

export type ChecksEngine = "generated_component" | "callout_component";

export type ChecksRequest = {
  // Which contract the code follows. Without it: `generated_component`.
  engine?: ChecksEngine;
  width: number;
  height: number;
  fps: number;
  frames: number;
  resolved: Record<string, unknown>;
  code: string;
  // The frames to draw. Without it the check draws the first, the middle and the last frame.
  at_frames?: number[];
};

export const checksRequestSchema = {
  type: "object",
  additionalProperties: false,
  required: ["width", "height", "fps", "frames", "resolved", "code"],
  properties: {
    engine: { type: "string", enum: ["generated_component", "callout_component"] },
    width: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    height: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    fps: { type: "integer", minimum: 1, maximum: 60 },
    frames: { type: "integer", minimum: 1, maximum: MAX_FRAMES },
    resolved: { type: "object" },
    code: { type: "string", minLength: 1, maxLength: MAX_CODE_CHARS },
    at_frames: {
      type: "array",
      minItems: 1,
      maxItems: MAX_CHECK_FRAMES,
      items: { type: "integer", minimum: 0, maximum: MAX_FRAMES - 1 },
    },
  },
} as const;

const BACKDROP = /^#[0-9a-fA-F]{6}$/;

// The rules of a render request that depend on more than one field. The JSON schema above accepts
// the widest request; this says which of those the service will draw. A readable message, or null.
export function requestProblem(request: RenderRequest): string | null {
  const { engine, encoding, frames, resolved } = request;
  const callout = isCalloutEngine(engine);
  // An evidence card (EVD-011) is an evidence clip with `resolved.card`: a transparent clip laid over
  // a shot, so it is ProRes 4444 like a callout, and only it may be.
  const card = engine === EVIDENCE_ENGINE && resolved["card"] !== undefined && resolved["card"] !== null;
  if (engine === EVIDENCE_ENGINE && (request.input === null || request.input === undefined)) {
    return "An evidence clip needs its images in `input`.";
  }
  if (engine === FOOTAGE_ENGINE && (request.input === null || request.input === undefined)) {
    return "A footage clip needs its picture in `input`.";
  }
  if (callout && frames > CALLOUT_MAX_FRAMES) {
    return `The engine "${engine}" draws at most ${CALLOUT_MAX_FRAMES} frames.`;
  }
  // The overlay of a sound bite (SB-009) is transparent: ProRes 4444 only.
  const overlay = engine === SOUNDBITE_ENGINE;
  if (overlay && frames > SOUNDBITE_MAX_FRAMES) {
    return `The engine "${engine}" draws at most ${SOUNDBITE_MAX_FRAMES} frames.`;
  }
  if (overlay && encoding.codec === "h264") {
    return "A sound bite overlay is transparent: it is drawn as ProRes 4444.";
  }
  if (encoding.codec === "h264") {
    if (encoding.pixel_format !== "yuv420p") return "H.264 is drawn as yuv420p.";
    if (encoding.crf === undefined || encoding.preset === undefined || encoding.color_space === undefined) {
      return "H.264 needs crf, preset and color_space.";
    }
    if (encoding.prores_profile !== undefined) return "prores_profile belongs to the prores codec.";
    if (card) return "An evidence card is transparent: it is drawn as ProRes 4444.";
    if (callout && !BACKDROP.test(String(resolved["backdrop"] ?? ""))) {
      return "An H.264 callout is a preview: resolved.backdrop must be a #RRGGBB colour, or the transparent areas would be black.";
    }
    return null;
  }
  if (!callout && !card && !overlay) {
    return `Only the callout engines, evidence cards and sound bite overlays may be drawn as ProRes; "${engine}" is H.264 only.`;
  }
  if (encoding.prores_profile !== "4444" || encoding.pixel_format !== "yuva444p10le") {
    return "ProRes needs prores_profile 4444 and pixel_format yuva444p10le.";
  }
  if (encoding.crf !== undefined || encoding.preset !== undefined) {
    return "crf and preset belong to the h264 codec.";
  }
  if (resolved["backdrop"] !== undefined) return "A ProRes clip is transparent: resolved.backdrop is for previews only.";
  return null;
}

// The rules of a check request that the JSON schema cannot hold.
export function checksProblem(request: ChecksRequest): string | null {
  const engine = request.engine ?? "generated_component";
  if (engine !== "callout_component") return null;
  if (request.frames > CALLOUT_MAX_FRAMES) {
    return `The engine "${engine}" is checked at most ${CALLOUT_MAX_FRAMES} frames long.`;
  }
  if (request.at_frames?.some((frame) => frame >= CALLOUT_MAX_FRAMES)) {
    return `The engine "${engine}" is checked at frames below ${CALLOUT_MAX_FRAMES}.`;
  }
  return null;
}
