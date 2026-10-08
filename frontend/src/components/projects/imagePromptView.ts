import type { Scene, ScenesState } from "../../api/scenes";

type PromptFields = Pick<
  Scene,
  "image_prompt" | "image_prompt_source" | "image_prompt_out_of_date" | "image_prompt_job"
>;

/** True while the newest job that writes the scene's image prompt is waiting or running. */
export function hasActiveImagePromptJob(scene: Pick<Scene, "image_prompt_job">): boolean {
  const job = scene.image_prompt_job;
  return job !== null && (job.status === "queued" || job.status === "running");
}

/** True when the scene holds an image prompt (any text, whoever wrote it). */
export function hasImagePrompt(scene: Pick<Scene, "image_prompt">): boolean {
  return scene.image_prompt !== null && scene.image_prompt.trim() !== "";
}

/**
 * What the scenes table says about a scene's image prompt: "Image prompt: none", "AI",
 * "AI, out of date", "yours" (the user wrote it) or "writing".
 */
export function imagePromptText(scene: PromptFields): string {
  if (hasActiveImagePromptJob(scene)) {
    return "Image prompt: writing";
  }
  if (!hasImagePrompt(scene)) {
    return "Image prompt: none";
  }
  if (scene.image_prompt_source !== "ai") {
    return "Image prompt: yours";
  }
  return scene.image_prompt_out_of_date ? "Image prompt: AI, out of date" : "Image prompt: AI";
}

/** True when the scene's newest image prompt job failed (and none is running now). */
export function imagePromptFailed(scene: Pick<Scene, "image_prompt_job">): boolean {
  return scene.image_prompt_job?.status === "failed";
}

export type ImagePromptCounts = {
  /** Scenes that hold an image prompt. */
  have: number;
  /** AI prompts written from inputs that have changed since. */
  outOfDate: number;
  /** Scenes whose prompt is being written (queued or running). */
  writing: number;
  /** Scenes whose newest prompt job failed. */
  failed: number;
};

export function imagePromptCounts(scenes: ScenesState["scenes"]): ImagePromptCounts {
  return {
    have: scenes.filter(hasImagePrompt).length,
    outOfDate: scenes.filter(
      (scene) => hasImagePrompt(scene) && scene.image_prompt_out_of_date,
    ).length,
    writing: scenes.filter(hasActiveImagePromptJob).length,
    failed: scenes.filter(imagePromptFailed).length,
  };
}

/** "9 of 15 scenes have an image prompt · 2 out of date · 3 being written · 1 failed". */
export function imagePromptCountsLine(counts: ImagePromptCounts, total: number): string {
  const parts = [`${counts.have} of ${total} ${total === 1 ? "scene has" : "scenes have"} an image prompt`];
  if (counts.outOfDate > 0) {
    parts.push(`${counts.outOfDate} out of date`);
  }
  if (counts.writing > 0) {
    parts.push(`${counts.writing} being written`);
  }
  if (counts.failed > 0) {
    parts.push(`${counts.failed} failed`);
  }
  return parts.join(" · ");
}
