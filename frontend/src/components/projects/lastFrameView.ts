import type { Scene, ScenesState } from "../../api/scenes";

type JobStatus = { status: string } | null;

function jobActive(job: JobStatus): boolean {
  return job !== null && (job.status === "queued" || job.status === "running");
}

/**
 * True when the scene gets a last frame: it has a description of one (the AI wrote it where an
 * end frame helps, or the user did), a prompt for it, or a frame in the slot. Most scenes do not.
 */
export function wantsLastFrame(
  scene: Pick<Scene, "last_frame_description" | "last_frame_prompt" | "last_frame">,
): boolean {
  return (
    (scene.last_frame_description !== null && scene.last_frame_description.trim() !== "") ||
    (scene.last_frame_prompt !== null && scene.last_frame_prompt.trim() !== "") ||
    scene.last_frame !== null
  );
}

// --- The last frame prompt (the instruction that edits the first frame) ------------------------

/** True while the newest job that writes the scene's last frame prompt is waiting or running. */
export function hasActiveLastFramePromptJob(
  scene: Pick<Scene, "last_frame_prompt_job">,
): boolean {
  return jobActive(scene.last_frame_prompt_job);
}

/** True when the scene holds a last frame prompt (any text, whoever wrote it). */
export function hasLastFramePrompt(scene: Pick<Scene, "last_frame_prompt">): boolean {
  return scene.last_frame_prompt !== null && scene.last_frame_prompt.trim() !== "";
}

/** True when the scene's newest last frame prompt job failed (and none is running now). */
export function lastFramePromptFailed(scene: Pick<Scene, "last_frame_prompt_job">): boolean {
  return scene.last_frame_prompt_job?.status === "failed";
}

/**
 * What the scenes table says about a scene's last frame prompt: "none", "AI", "AI, out of
 * date", "yours" or "writing".
 */
export function lastFramePromptText(
  scene: Pick<
    Scene,
    | "last_frame_prompt"
    | "last_frame_prompt_source"
    | "last_frame_prompt_out_of_date"
    | "last_frame_prompt_job"
  >,
): string {
  if (hasActiveLastFramePromptJob(scene)) {
    return "Last frame prompt: writing";
  }
  if (!hasLastFramePrompt(scene)) {
    return "Last frame prompt: none";
  }
  if (scene.last_frame_prompt_source !== "ai") {
    return "Last frame prompt: yours";
  }
  return scene.last_frame_prompt_out_of_date
    ? "Last frame prompt: AI, out of date"
    : "Last frame prompt: AI";
}

// --- The last frame itself -----------------------------------------------------------------

/** True while the newest job that makes the scene's last frame is waiting or running. */
export function hasActiveLastFrameJob(scene: Pick<Scene, "last_frame_job">): boolean {
  return jobActive(scene.last_frame_job);
}

/** True when the scene's newest last frame job failed (and none is running now). */
export function lastFrameFailed(scene: Pick<Scene, "last_frame_job">): boolean {
  return scene.last_frame_job?.status === "failed";
}

/** True when the scene's last frame is one the image model made. */
export function hasAiLastFrame(scene: Pick<Scene, "last_frame">): boolean {
  return scene.last_frame?.source === "ai";
}

/**
 * What the scenes table says about a scene's last frame: "none yet", "uploaded", "AI",
 * "AI, out of date" or "being made".
 */
export function lastFrameText(
  scene: Pick<Scene, "last_frame" | "last_frame_out_of_date" | "last_frame_job">,
): string {
  if (hasActiveLastFrameJob(scene)) {
    return "Last frame: being made";
  }
  if (scene.last_frame === null) {
    return "Last frame: none yet";
  }
  if (scene.last_frame.source !== "ai") {
    return "Last frame: uploaded";
  }
  return scene.last_frame_out_of_date ? "Last frame: AI, out of date" : "Last frame: AI";
}

export type LastFrameCounts = {
  /** Scenes that get a last frame (see `wantsLastFrame`). */
  planned: number;
  /** Of those, the ones that hold a last frame prompt. */
  prompts: number;
  /** AI prompts written from inputs that have changed since. */
  promptsOutOfDate: number;
  /** Scenes whose prompt is being written (queued or running). */
  promptsWriting: number;
  /** Scenes that have a last frame, whoever made it. */
  have: number;
  /** Of those, the ones the image model made. */
  ai: number;
  /** Of those, the ones the user uploaded. */
  uploaded: number;
  /** AI last frames made from a prompt or a first frame that has changed since. */
  outOfDate: number;
  /** Scenes whose last frame is being made (queued or running). */
  making: number;
  /** Scenes whose newest last frame job (or prompt job) failed. */
  failed: number;
};

export function lastFrameCounts(scenes: ScenesState["scenes"]): LastFrameCounts {
  const planned = scenes.filter(wantsLastFrame);
  const have = planned.filter((scene) => scene.last_frame !== null);
  const ai = have.filter(hasAiLastFrame);
  return {
    planned: planned.length,
    prompts: planned.filter(hasLastFramePrompt).length,
    promptsOutOfDate: planned.filter(
      (scene) => hasLastFramePrompt(scene) && scene.last_frame_prompt_out_of_date,
    ).length,
    promptsWriting: planned.filter(hasActiveLastFramePromptJob).length,
    have: have.length,
    ai: ai.length,
    uploaded: have.length - ai.length,
    outOfDate: ai.filter((scene) => scene.last_frame_out_of_date).length,
    making: planned.filter(hasActiveLastFrameJob).length,
    failed: planned.filter((scene) => lastFrameFailed(scene) || lastFramePromptFailed(scene))
      .length,
  };
}

/** "3 of 15 scenes get a last frame · 2 have a prompt · 1 has a frame (1 AI) · 1 being made". */
export function lastFrameCountsLine(counts: LastFrameCounts): string {
  const scenes = (n: number) => (n === 1 ? "scene gets" : "scenes get");
  const parts = [`${counts.planned} ${scenes(counts.planned)} a last frame`];
  parts.push(`${counts.prompts} ${counts.prompts === 1 ? "has" : "have"} a prompt`);
  if (counts.promptsOutOfDate > 0) {
    parts.push(`${counts.promptsOutOfDate} out of date`);
  }
  if (counts.promptsWriting > 0) {
    parts.push(`${counts.promptsWriting} being written`);
  }
  parts.push(
    `${counts.have} ${counts.have === 1 ? "has" : "have"} a frame ` +
      `(${counts.ai} AI, ${counts.uploaded} uploaded)`,
  );
  if (counts.outOfDate > 0) {
    parts.push(`${counts.outOfDate} frames out of date`);
  }
  if (counts.making > 0) {
    parts.push(`${counts.making} being made`);
  }
  if (counts.failed > 0) {
    parts.push(`${counts.failed} failed`);
  }
  return parts.join(" · ");
}
