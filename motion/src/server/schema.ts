// The JSON schema of POST /renders. Fastify checks the body against it before any handler runs,
// so a malformed request never reaches Remotion.

export const ENGINES = [
  "test_card",
  "remotion_templates",
  "remotion_blocks",
  "generated_component",
] as const;
export type Engine = (typeof ENGINES)[number];

export const MAX_FRAMES = 720;
export const MAX_TIME_LIMIT_S = 900;

export type Encoding = {
  codec: "h264";
  crf: number;
  preset: string;
  pixel_format: "yuv420p";
  color_space: "bt709";
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
    frames: { type: "integer", minimum: 1, maximum: MAX_FRAMES },
    resolved: { type: "object" },
    input: {},
    code: { type: ["string", "null"], maxLength: 100_000 },
    encoding: {
      type: "object",
      additionalProperties: false,
      required: ["codec", "crf", "preset", "pixel_format", "color_space"],
      properties: {
        codec: { type: "string", enum: ["h264"] },
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
        pixel_format: { type: "string", enum: ["yuv420p"] },
        color_space: { type: "string", enum: ["bt709"] },
      },
    },
    time_limit_s: { type: "integer", minimum: 10, maximum: MAX_TIME_LIMIT_S },
  },
} as const;

// The body of POST /layout (GFX-009): the size, length and resolved brief of a render, the block
// scene as its `input`, and the frames at which to report the texts on the screen.
export type LayoutRequest = {
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
    width: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    height: { type: "integer", minimum: 64, maximum: 4096, multipleOf: 2 },
    fps: { type: "integer", minimum: 1, maximum: 60 },
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
