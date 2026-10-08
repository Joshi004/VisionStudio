import type { Scene, ScenesState } from "../../api/scenes";

type FrameFields = Pick<Scene, "first_frame" | "first_frame_out_of_date" | "frame_job">;

/** True while the newest job that makes the scene's first frame is waiting or running. */
export function hasActiveFrameJob(scene: Pick<Scene, "frame_job">): boolean {
  const job = scene.frame_job;
  return job !== null && (job.status === "queued" || job.status === "running");
}

/** True when the scene's newest first frame job failed (and none is running now). */
export function frameFailed(scene: Pick<Scene, "frame_job">): boolean {
  return scene.frame_job?.status === "failed";
}

/** True when the scene's first frame is one the image model made. */
export function hasAiFrame(scene: Pick<Scene, "first_frame">): boolean {
  return scene.first_frame?.source === "ai";
}

/**
 * What the scenes table says about a scene's first frame: "First frame: none", "uploaded", "AI",
 * "AI, out of date" or "being made".
 */
export function firstFrameText(scene: FrameFields): string {
  if (hasActiveFrameJob(scene)) {
    return "First frame: being made";
  }
  if (scene.first_frame === null) {
    return "First frame: none";
  }
  if (scene.first_frame.source !== "ai") {
    return "First frame: uploaded";
  }
  return scene.first_frame_out_of_date ? "First frame: AI, out of date" : "First frame: AI";
}

export type FirstFrameCounts = {
  /** Scenes that have a first frame, whoever made it. */
  have: number;
  /** Of those, the ones the image model made. */
  ai: number;
  /** Of those, the ones the user uploaded. */
  uploaded: number;
  /** AI frames made from an image prompt that has changed since. */
  outOfDate: number;
  /** Scenes whose first frame is being made (queued or running). */
  making: number;
  /** Scenes whose newest first frame job failed. */
  failed: number;
};

export function firstFrameCounts(scenes: ScenesState["scenes"]): FirstFrameCounts {
  const have = scenes.filter((scene) => scene.first_frame !== null);
  const ai = have.filter(hasAiFrame);
  return {
    have: have.length,
    ai: ai.length,
    uploaded: have.length - ai.length,
    outOfDate: ai.filter((scene) => scene.first_frame_out_of_date).length,
    making: scenes.filter(hasActiveFrameJob).length,
    failed: scenes.filter(frameFailed).length,
  };
}

/** "9 of 15 scenes have a first frame (3 AI, 6 uploaded) · 1 out of date · 2 being made". */
export function firstFrameCountsLine(counts: FirstFrameCounts, total: number): string {
  const parts = [
    `${counts.have} of ${total} ${total === 1 ? "scene has" : "scenes have"} a first frame ` +
      `(${counts.ai} AI, ${counts.uploaded} uploaded)`,
  ];
  if (counts.outOfDate > 0) {
    parts.push(`${counts.outOfDate} out of date`);
  }
  if (counts.making > 0) {
    parts.push(`${counts.making} being made`);
  }
  if (counts.failed > 0) {
    parts.push(`${counts.failed} failed`);
  }
  return parts.join(" · ");
}

/** "$0.32": the estimated cost of `count` images at `pricePerImage` dollars each. */
export function estimatedCost(count: number, pricePerImage: number): string {
  return `$${(count * pricePerImage).toFixed(2)}`;
}
