import { randomUUID } from "node:crypto";
import { mkdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { makeCancelSignal, renderMedia, selectComposition } from "@remotion/renderer";
import type { Engine, RenderRequest } from "./schema.ts";
import { transpile } from "./transpile.ts";

const root = resolve(import.meta.dirname, "../..");
export const BUNDLE_DIR = process.env["MOTION_BUNDLE"] ?? resolve(root, "build/bundle");
const RENDER_DIR = join(tmpdir(), "motion-renders");

// How many renders run at once. The backend sends only as many as its own setting allows; the
// rest wait here in the order they arrived.
export const MAX_PARALLEL = clamp(Number(process.env["MOTION_MAX_PARALLEL"] ?? 4), 1, 8);
// A finished or failed render is removed this long after it ended, whether it was fetched or not.
const KEEP_MS = 30 * 60 * 1000;
// The wait for one frame's resources (a font, an image) before the render fails.
const FRAME_WAIT_MS = 30_000;
// Chrome tabs per render: enough to be quick, few enough for the container's memory.
const BROWSER_TABS = 2;

const COMPOSITION_OF: Record<Engine, string> = {
  test_card: "TestCard",
  remotion_templates: "Templates",
  remotion_blocks: "Blocks",
  generated_component: "Generated",
  callout_component: "Callout",
  callout_blocks: "Callout",
};

export type RenderState = "queued" | "rendering" | "done" | "failed";

type RenderRecord = {
  id: string;
  request: RenderRequest;
  state: RenderState;
  progress: number;
  error: string | null;
  createdAt: number;
  startedAt: number | null;
  finishedAt: number | null;
  file: string;
  cancel: (() => void) | null;
  removed: boolean;
};

const records = new Map<string, RenderRecord>();
const waiting: string[] = [];
let running = 0;

function clamp(value: number, low: number, high: number): number {
  return Number.isFinite(value) ? Math.min(high, Math.max(low, Math.trunc(value))) : low;
}

export function prepareRenderDir(): void {
  rmSync(RENDER_DIR, { recursive: true, force: true });
  mkdirSync(RENDER_DIR, { recursive: true });
}

export function enqueue(request: RenderRequest): string {
  const id = randomUUID();
  records.set(id, {
    id,
    request,
    state: "queued",
    progress: 0,
    error: null,
    createdAt: Date.now(),
    startedAt: null,
    finishedAt: null,
    // Remotion needs the extension of the container: .mov for ProRes (a callout with an alpha channel).
    file: join(RENDER_DIR, `${id}.${request.encoding.codec === "prores" ? "mov" : "mp4"}`),
    cancel: null,
    removed: false,
  });
  waiting.push(id);
  pump();
  return id;
}

function pump(): void {
  while (running < MAX_PARALLEL) {
    const id = waiting.shift();
    if (id === undefined) return;
    const record = records.get(id);
    if (record === undefined || record.removed) continue;
    running += 1;
    void run(record).finally(() => {
      running -= 1;
      pump();
    });
  }
}

async function run(record: RenderRecord): Promise<void> {
  const { request } = record;
  record.state = "rendering";
  record.startedAt = Date.now();

  const { cancelSignal, cancel } = makeCancelSignal();
  let timedOut = false;
  record.cancel = cancel;
  const timer = setTimeout(() => {
    timedOut = true;
    cancel();
  }, request.time_limit_s * 1000);

  // A generated component (and a callout's) is transpiled here, once, and the composition
  // evaluates the result (GFX-010). Code that does not compile fails the render before any browser
  // starts.
  let compiled: string | null = null;
  if (request.engine === "generated_component" || request.engine === "callout_component") {
    const transpiled = await transpile(request.code ?? "");
    if (transpiled.error !== undefined) {
      clearTimeout(timer);
      record.cancel = null;
      record.state = "failed";
      record.error = `The component does not compile: ${transpiled.error}`;
      record.finishedAt = Date.now();
      return;
    }
    compiled = transpiled.js;
  }

  const inputProps = {
    engine: request.engine,
    width: request.width,
    height: request.height,
    fps: request.fps,
    frames: request.frames,
    resolved: request.resolved,
    input: request.input ?? null,
    code: request.code ?? null,
    compiled,
  };

  const draw = async (): Promise<void> => {
    const composition = await selectComposition({
      serveUrl: BUNDLE_DIR,
      id: COMPOSITION_OF[request.engine],
      inputProps,
      logLevel: "warn",
      timeoutInMilliseconds: FRAME_WAIT_MS,
    });
    if (
      composition.width !== request.width ||
      composition.height !== request.height ||
      composition.fps !== request.fps ||
      composition.durationInFrames !== request.frames
    ) {
      throw new Error("The composition did not take the size and length that were asked for.");
    }
    await renderMedia({
      composition,
      serveUrl: BUNDLE_DIR,
      outputLocation: record.file,
      inputProps,
      ...encodingOptions(request),
      // PNG frames: JPEG would lose detail before the encoder sees it.
      imageFormat: "png",
      muted: true,
      concurrency: BROWSER_TABS,
      timeoutInMilliseconds: FRAME_WAIT_MS,
      cancelSignal,
      logLevel: "warn",
      overwrite: true,
      onProgress: ({ progress }) => {
        record.progress = Math.round(progress * 1000) / 1000;
      },
    });
  };

  try {
    try {
      await draw();
    } catch (error) {
      // Remotion starts a small file server for each render. When one render follows another
      // very closely, the browser sometimes finds the earlier server still closing and its
      // connection is reset (seen twice in about 60 renders in GFX-007). Nothing was wrong with
      // the input, so the render is tried once more; any other error is final.
      if (timedOut || record.removed || !errorText(error).includes("ERR_CONNECTION_RESET")) {
        throw error;
      }
      record.progress = 0;
      await draw();
    }
    record.progress = 1;
    record.state = "done";
  } catch (error) {
    rmSync(record.file, { force: true });
    record.state = "failed";
    record.error = timedOut
      ? `The render ran past its time limit of ${request.time_limit_s} s and was stopped.`
      : record.removed
        ? "The render was cancelled."
        : failureText(error);
  } finally {
    clearTimeout(timer);
    record.cancel = null;
    record.finishedAt = Date.now();
  }
}

// The encoder's options of Remotion for the request's encoding. H.264 is as it always was. ProRes
// 4444 takes no CRF and no x264 preset, and keeps the alpha channel the PNG frames carry.
function encodingOptions(request: RenderRequest) {
  const { encoding } = request;
  if (encoding.codec === "prores") {
    return {
      codec: "prores" as const,
      proResProfile: "4444" as const,
      pixelFormat: "yuva444p10le" as const,
      colorSpace: "bt709" as const,
    };
  }
  return {
    codec: "h264" as const,
    crf: encoding.crf ?? 18,
    x264Preset: (encoding.preset ?? "medium") as "medium",
    pixelFormat: "yuv420p" as const,
    colorSpace: "bt709" as const,
  };
}

function errorText(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  return text.slice(0, 2000);
}

// Remotion's error for a frame that threw carries the frame's number (`frame`). It is put in front
// of the message so that the repair of a component can say where it broke (EXG-006).
function failureText(error: unknown): string {
  const frame = (error as { frame?: unknown } | null)?.frame;
  const text = errorText(error);
  return typeof frame === "number" && Number.isInteger(frame) ? `At frame ${frame}: ${text}`.slice(0, 2000) : text;
}

export type RenderStatus = {
  state: RenderState;
  progress: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  render_s: number | null;
};

export function statusOf(id: string): RenderStatus | null {
  const record = records.get(id);
  if (record === undefined) return null;
  return {
    state: record.state,
    progress: record.progress,
    error: record.error,
    created_at: new Date(record.createdAt).toISOString(),
    started_at: record.startedAt === null ? null : new Date(record.startedAt).toISOString(),
    finished_at: record.finishedAt === null ? null : new Date(record.finishedAt).toISOString(),
    render_s:
      record.startedAt !== null && record.finishedAt !== null
        ? Math.round(((record.finishedAt - record.startedAt) / 1000) * 1000) / 1000
        : null,
  };
}

// The finished file and its size, or null when the render is unknown or not done.
export function fileOf(id: string): { path: string; size: number; contentType: string } | null {
  const record = records.get(id);
  if (record === undefined || record.state !== "done") return null;
  try {
    const contentType = record.file.endsWith(".mov") ? "video/quicktime" : "video/mp4";
    return { path: record.file, size: statSync(record.file).size, contentType };
  } catch {
    return null;
  }
}

// Stops the render if it is running, removes its file and forgets it. False when it is unknown.
export function remove(id: string): boolean {
  const record = records.get(id);
  if (record === undefined) return false;
  record.removed = true;
  record.cancel?.();
  rmSync(record.file, { force: true });
  records.delete(id);
  return true;
}

export function sweep(now = Date.now()): void {
  for (const record of [...records.values()]) {
    if (record.finishedAt !== null && now - record.finishedAt > KEEP_MS) remove(record.id);
  }
}

export function counts(): { queued: number; rendering: number } {
  return { queued: waiting.length, rendering: running };
}
