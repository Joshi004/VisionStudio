import type { ProjectDetail, ProjectUpdate } from "../../api/projects";

export type NumberDraft = number | string;

export type Draft = {
  name: string;
  gen_width: NumberDraft;
  gen_height: NumberDraft;
  out_width: NumberDraft;
  out_height: NumberDraft;
  fps: NumberDraft;
  min_scene_seconds: NumberDraft;
  max_scene_seconds: NumberDraft;
  /** In percent, because that is how the page shows it. The API takes 0 to 1. */
  clip_sound_percent: NumberDraft;
  style_prefix: string;
  prompt_suffix: string;
  negative_prompt: string;
  cut_instructions: string;
  description_instructions: string;
};

export const NUMBER_FIELDS = [
  "gen_width",
  "gen_height",
  "out_width",
  "out_height",
  "fps",
  "min_scene_seconds",
  "max_scene_seconds",
] as const;

const TEXT_FIELDS = [
  "name",
  "style_prefix",
  "prompt_suffix",
  "negative_prompt",
  "cut_instructions",
  "description_instructions",
] as const;

function toPercent(volume: number): number {
  return Math.round(volume * 100);
}

export function initialDraft(project: ProjectDetail): Draft {
  return {
    name: project.name,
    gen_width: project.gen_width,
    gen_height: project.gen_height,
    out_width: project.out_width,
    out_height: project.out_height,
    fps: project.fps,
    min_scene_seconds: project.min_scene_seconds,
    max_scene_seconds: project.max_scene_seconds,
    clip_sound_percent: toPercent(project.clip_sound_volume),
    style_prefix: project.style_prefix ?? "",
    prompt_suffix: project.prompt_suffix ?? "",
    negative_prompt: project.negative_prompt ?? "",
    cut_instructions: project.cut_instructions ?? "",
    description_instructions: project.description_instructions ?? "",
  };
}

/**
 * Only the fields that differ from the saved project. An emptied number box is
 * sent as null, so the server's own "cannot be empty" message is what shows.
 */
export function changedFields(project: ProjectDetail, draft: Draft): ProjectUpdate {
  const saved = initialDraft(project);
  const changes: ProjectUpdate = {};

  for (const field of TEXT_FIELDS) {
    if (draft[field] !== saved[field]) {
      changes[field] = draft[field];
    }
  }
  for (const field of NUMBER_FIELDS) {
    if (draft[field] !== saved[field]) {
      changes[field] = draft[field] === "" ? null : Number(draft[field]);
    }
  }
  if (draft.clip_sound_percent !== saved.clip_sound_percent) {
    changes.clip_sound_volume =
      draft.clip_sound_percent === "" ? null : Number(draft.clip_sound_percent) / 100;
  }
  return changes;
}

/** A key that changes whenever the saved settings do, so the form restarts from them. */
export function settingsKey(project: ProjectDetail): string {
  return JSON.stringify(initialDraft(project));
}
