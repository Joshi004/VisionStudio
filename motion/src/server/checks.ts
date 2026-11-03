import { openBrowser, renderStill, selectComposition } from "@remotion/renderer";
import type { HeadlessBrowser } from "@remotion/renderer";

import { TEXT_MARKER } from "../generated/marker.ts";
import { BUNDLE_DIR } from "./renders.ts";
import type { ChecksRequest } from "./schema.ts";
import { transpile } from "./transpile.ts";

// The longest one check may take, browser start included, and the wait for one frame's resources.
// The limit is for the usual three frames; each frame above three adds EXTRA_FRAME_MS (EXG-006), so
// 73 s at 16 frames. Sixteen frames of the longest components (25,000 characters, 720 frames) took
// 2.4 to 2.7 s, about 0.15 s a frame, so this is a wide margin; a frame that never finishes ends
// the check by itself after FRAME_WAIT_MS.
const TIME_LIMIT_MS = 60_000;
const USUAL_FRAMES = 3;
const EXTRA_FRAME_MS = 1_000;
const FRAME_WAIT_MS = 20_000;

export type CheckError = { frame: number | null; message: string };
export type ChecksResult = {
  ok: boolean;
  // Where the first error is: "transpile" (the code does not compile) or "render" (a still failed).
  stage: "transpile" | "render" | null;
  errors: CheckError[];
  // The text on screen at each frame that was drawn.
  texts: { frame: number; text: string }[];
  check_s: number;
};

// The check itself could not run (no browser), which says nothing about the component.
export class ServiceError extends Error {}

// One check at a time: each starts a browser, and the work is short.
let queue: Promise<unknown> = Promise.resolve();

function errorText(error: unknown): string {
  return (error instanceof Error ? error.message : String(error)).slice(0, 2000);
}

// Remotion's own message for a page that never finishes says only that a timeout passed.
function withTimeoutHint(message: string): string {
  return /timeout|timed out/i.test(message)
    ? `${message} The component probably never finishes drawing (an endless loop, or a delayRender that is never continued).`
    : message;
}

// The first, the middle and the last frame (§4.5.3).
export function checkFrames(frames: number): number[] {
  return [...new Set([0, Math.floor(frames / 2), frames - 1])];
}

// The frames a check draws: the ones the request names (only those inside the clip, each once, in
// order), or the usual three.
export function framesToDraw(request: ChecksRequest): number[] {
  if (request.at_frames === undefined) return checkFrames(request.frames);
  const named = [...new Set(request.at_frames)].filter((frame) => frame < request.frames);
  return named.length > 0 ? named.sort((a, b) => a - b) : checkFrames(request.frames);
}

function timeLimitMs(drawn: number): number {
  return TIME_LIMIT_MS + Math.max(0, drawn - USUAL_FRAMES) * EXTRA_FRAME_MS;
}

async function drawStills(
  request: ChecksRequest,
  frames: number[],
  js: string,
  browser: HeadlessBrowser,
): Promise<ChecksResult> {
  const result: ChecksResult = { ok: true, stage: null, errors: [], texts: [], check_s: 0 };
  const inputProps = {
    engine: "generated_component",
    width: request.width,
    height: request.height,
    fps: request.fps,
    frames: request.frames,
    resolved: request.resolved,
    input: null,
    code: null,
    compiled: js,
    report_text: true,
  };
  const composition = await selectComposition({
    serveUrl: BUNDLE_DIR,
    id: "Generated",
    inputProps,
    puppeteerInstance: browser,
    logLevel: "warn",
    timeoutInMilliseconds: FRAME_WAIT_MS,
  });
  for (const frame of frames) {
    try {
      await renderStill({
        serveUrl: BUNDLE_DIR,
        composition,
        frame,
        inputProps,
        output: null,
        imageFormat: "png",
        puppeteerInstance: browser,
        logLevel: "warn",
        timeoutInMilliseconds: FRAME_WAIT_MS,
        onBrowserLog: (log) => {
          if (!log.text.startsWith(TEXT_MARKER)) return;
          try {
            const seen = JSON.parse(log.text.slice(TEXT_MARKER.length)) as { frame: number; text: string };
            result.texts.push({ frame: seen.frame, text: seen.text });
          } catch {
            // A component that wrote something like the marker is not an error.
          }
        },
      });
    } catch (error) {
      result.ok = false;
      result.stage = "render";
      result.errors.push({ frame, message: withTimeoutHint(errorText(error)) });
      // The same error would repeat at the next frames.
      break;
    }
  }
  return result;
}

async function checkOnce(request: ChecksRequest): Promise<ChecksResult> {
  const started = Date.now();
  const done = (result: ChecksResult): ChecksResult => ({
    ...result,
    check_s: Math.round(((Date.now() - started) / 1000) * 1000) / 1000,
  });

  const transpiled = await transpile(request.code);
  if (transpiled.error !== undefined) {
    return done({
      ok: false,
      stage: "transpile",
      errors: [{ frame: null, message: transpiled.error }],
      texts: [],
      check_s: 0,
    });
  }

  // The check's own browser: when the time limit passes, closing it ends a page that is stuck in
  // a loop, and no other render is touched.
  const browser = await openBrowser("chrome", { logLevel: "warn" }).catch((error: unknown) => {
    throw new ServiceError(`The browser could not be started: ${errorText(error)}`);
  });
  const frames = framesToDraw(request);
  const limitMs = timeLimitMs(frames.length);
  let timer: NodeJS.Timeout | undefined;
  const limit = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`The component ran past the time limit of ${limitMs / 1000} s (an endless loop?).`)),
      limitMs,
    );
  });
  const work = drawStills(request, frames, transpiled.js, browser);
  // The work may still fail after the limit has won the race; that is not an unhandled error.
  work.catch(() => undefined);
  try {
    return done(await Promise.race([work, limit]));
  } finally {
    clearTimeout(timer);
    await browser.close({ silent: true }).catch(() => undefined);
  }
}

// Transpiles a component and draws it at three frames (or the frames the request names), answering what went wrong. An error in the
// component is an answer (`ok: false`); only a failure of the service itself (`ServiceError`) throws.
export function checkComponent(request: ChecksRequest): Promise<ChecksResult> {
  const run = async (): Promise<ChecksResult> => {
    try {
      return await checkOnce(request);
    } catch (error) {
      // The same rare reset as in a render (see `run` in renders.ts): once more, then final.
      if (errorText(error).includes("ERR_CONNECTION_RESET")) return checkOnce(request);
      throw error;
    }
  };
  const next = queue.then(run, run);
  queue = next.catch(() => undefined);
  return next.catch((error: unknown) => {
    if (error instanceof ServiceError) throw error;
    // Anything else is the component's: it hung, or the browser gave up on it.
    return {
      ok: false,
      stage: "render" as const,
      errors: [{ frame: null, message: errorText(error) }],
      texts: [],
      check_s: 0,
    };
  });
}
