// The JSON schema of POST /renders. Fastify checks the body against it before any handler runs,
// so a malformed request never reaches Remotion.

export const ENGINES = [
  "test_card",
  "remotion_templates",
  "remotion_blocks",
  "generated_component",
  "callout_component",
  "callout_blocks",
] as const;
export type Engine = (typeof ENGINES)[number];

// The engines that draw a callout (CMO-001): a transparent clip laid over a shot. Only they may be
// asked for ProRes 4444, and only they may be longer than MAX_FRAMES. `callout_blocks` (CMO-004)
// draws the block scene of a callout.
export const CALLOUT_ENGINES: readonly Engine[] = ["callout_component", "callout_blocks"];

export function isCalloutEngine(engine: Engine): boolean {
  return CALLOUT_ENGINES.includes(engine);
}

export const MAX_FRAMES = 720;
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
    // The most any engine may ask for; `requestProblem` holds the other engines to MAX_FRAMES.
    frames: { type: "integer", minimum: 1, maximum: CALLOUT_MAX_FRAMES },
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
    // The most any mode may ask for; `layoutProblem` holds a shot's scene to MAX_FRAMES.
    frames: { type: "integer", minimum: 1, maximum: CALLOUT_MAX_FRAMES },
    resolved: { type: "object" },
    input: {},
    at_frames: {
      type: "array",
      minItems: 1,
      maxItems: MAX_LAYOUT_FRAMES,
      items: { type: "integer", minimum: 0, maximum: CALLOUT_MAX_FRAMES - 1 },
    },
  },
} as const;

// The rules of a layout request that the JSON schema cannot hold. A readable message, or null.
export function layoutProblem(request: LayoutRequest): string | null {
  if (request.mode === "callout") return null;
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
    frames: { type: "integer", minimum: 1, maximum: CALLOUT_MAX_FRAMES },
    resolved: { type: "object" },
    code: { type: "string", minLength: 1, maxLength: MAX_CODE_CHARS },
    at_frames: {
      type: "array",
      minItems: 1,
      maxItems: MAX_CHECK_FRAMES,
      items: { type: "integer", minimum: 0, maximum: CALLOUT_MAX_FRAMES - 1 },
    },
  },
} as const;

const BACKDROP = /^#[0-9a-fA-F]{6}$/;

// The rules of a render request that depend on more than one field. The JSON schema above accepts
// the widest request; this says which of those the service will draw. A readable message, or null.
export function requestProblem(request: RenderRequest): string | null {
  const { engine, encoding, frames, resolved } = request;
  const callout = isCalloutEngine(engine);
  if (!callout && frames > MAX_FRAMES) {
    return `The engine "${engine}" draws at most ${MAX_FRAMES} frames.`;
  }
  if (encoding.codec === "h264") {
    if (encoding.pixel_format !== "yuv420p") return "H.264 is drawn as yuv420p.";
    if (encoding.crf === undefined || encoding.preset === undefined || encoding.color_space === undefined) {
      return "H.264 needs crf, preset and color_space.";
    }
    if (encoding.prores_profile !== undefined) return "prores_profile belongs to the prores codec.";
    if (callout && !BACKDROP.test(String(resolved["backdrop"] ?? ""))) {
      return "An H.264 callout is a preview: resolved.backdrop must be a #RRGGBB colour, or the transparent areas would be black.";
    }
    return null;
  }
  if (!callout) return `Only the callout engines may be drawn as ProRes; "${engine}" is H.264 only.`;
  if (encoding.prores_profile !== "4444" || encoding.pixel_format !== "yuva444p10le") {
    return "ProRes needs prores_profile 4444 and pixel_format yuva444p10le.";
  }
  if (encoding.crf !== undefined || encoding.preset !== undefined) {
    return "crf and preset belong to the h264 codec.";
  }
  if (resolved["backdrop"] !== undefined) return "A ProRes callout is transparent: resolved.backdrop is for previews only.";
  return null;
}

// The rules of a check request that the JSON schema cannot hold.
export function checksProblem(request: ChecksRequest): string | null {
  const engine = request.engine ?? "generated_component";
  if (engine !== "callout_component" && request.frames > MAX_FRAMES) {
    return `The engine "${engine}" is checked at most ${MAX_FRAMES} frames long.`;
  }
  return null;
}
