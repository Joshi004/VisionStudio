import { selectComposition } from "@remotion/renderer";

import type { LayoutReport } from "../blocks/report.ts";
import { BUNDLE_DIR } from "./renders.ts";
import type { LayoutRequest } from "./schema.ts";

// The longest one layout may take, browser start included, and the wait for the page.
const TIME_LIMIT_MS = 60_000;
const PAGE_WAIT_MS = 30_000;

// One layout at a time: each starts a browser, and the work is short.
let queue: Promise<unknown> = Promise.resolve();

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function measureOnce(request: LayoutRequest): Promise<LayoutReport> {
  let timer: NodeJS.Timeout | undefined;
  const limit = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`The layout check ran past its time limit of ${TIME_LIMIT_MS / 1000} s.`)),
      TIME_LIMIT_MS,
    );
  });
  const work = selectComposition({
    serveUrl: BUNDLE_DIR,
    id: "BlocksLayout",
    inputProps: {
      engine: "remotion_blocks",
      width: request.width,
      height: request.height,
      fps: request.fps,
      frames: request.frames,
      resolved: request.resolved,
      input: request.input,
      code: null,
      at_frames: request.at_frames,
      report: null,
    },
    logLevel: "warn",
    timeoutInMilliseconds: PAGE_WAIT_MS,
  });
  try {
    const composition = await Promise.race([work, limit]);
    const report = composition.props["report"];
    if (typeof report !== "object" || report === null) {
      throw new Error("The browser gave no layout report.");
    }
    return report as LayoutReport;
  } finally {
    clearTimeout(timer);
  }
}

// Asks the browser for the boxes of the texts of a block scene at the given frames. The error is
// the browser's own, for example a scene the block library cannot draw.
export function measureLayout(request: LayoutRequest): Promise<LayoutReport> {
  const run = async (): Promise<LayoutReport> => {
    try {
      return await measureOnce(request);
    } catch (error) {
      // The same rare reset as in a render (see `run` in renders.ts): once more, then final.
      if (!errorText(error).includes("ERR_CONNECTION_RESET")) throw error;
      return measureOnce(request);
    }
  };
  const next = queue.then(run, run);
  queue = next.catch(() => undefined);
  return next;
}
