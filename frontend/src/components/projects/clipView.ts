import type { Take } from "../../api/clips";
import type { Scene } from "../../api/scenes";
import { videoModelLabel } from "../../videoModels";

/** True while the scene's newest clip job is waiting or running. */
export function hasActiveClipJob(scene: Pick<Scene, "clip_job">): boolean {
  const job = scene.clip_job;
  return job !== null && (job.status === "queued" || job.status === "running");
}

/** "Regenerate" once the scene has a clip, "Generate" before. */
export function generateLabel(scene: Pick<Scene, "takes">): string {
  return scene.takes.length > 0 ? "Regenerate" : "Generate";
}

/**
 * What the scenes table says about a scene's clip when nothing is running:
 * "No clip", "Take 2 of 3", or "3 takes, none selected" (the selection was cleared).
 */
export function clipCell(scene: Pick<Scene, "takes">): string {
  const { takes } = scene;
  if (takes.length === 0) {
    return "No clip";
  }
  // Newest first, so the oldest take is take 1.
  const selectedIndex = takes.findIndex((take) => take.selected);
  if (selectedIndex < 0) {
    return `${takes.length} ${takes.length === 1 ? "take" : "takes"}, none selected`;
  }
  return `Take ${takes.length - selectedIndex} of ${takes.length}`;
}

/** How a scene's clip is made: from its first frame alone, or from both frames. */
export function clipModeText(mode: Scene["clip_mode"]): string {
  return mode === "first_and_last" ? "First and last frame" : "First frame only";
}

/** Which level chose the model that makes the scene's next clip, for a hint under the choice. */
export function modelSourceText(source: Scene["effective_video_model_source"]): string {
  if (source === "scene") {
    return "chosen for this scene";
  }
  return source === "project" ? "the project's choice" : "the app's default";
}

/**
 * "LTX-2.5 quality · first frame only · seed 1527961933 · 81 frames · 3.38 s · sound: aac".
 * An older clip that recorded no model is told by its endpoint, so it starts with LTX-2.3.
 */
export function takeLine(take: Take): string {
  const parts: string[] = [];
  if (take.video_model !== null) {
    const name = videoModelLabel(take.video_model);
    parts.push(take.mode !== null ? `${name} ${take.mode}` : name);
  }
  if (take.clip_mode !== null) {
    parts.push(clipModeText(take.clip_mode).toLowerCase());
  }
  if (take.seed !== null) {
    parts.push(`seed ${take.seed}`);
  }
  if (take.frame_count !== null) {
    parts.push(`${take.frame_count} frames`);
  }
  if (take.duration_s !== null) {
    parts.push(`${take.duration_s.toFixed(2)} s`);
  }
  parts.push(take.audio_codec !== null ? `sound: ${take.audio_codec}` : "no sound");
  return parts.join(" · ");
}
