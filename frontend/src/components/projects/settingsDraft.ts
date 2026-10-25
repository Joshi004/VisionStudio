import type { ProjectDetail, ProjectUpdate } from "../../api/projects";

export type NumberDraft = number | string;

export type Draft = {
  name: string;
  gen_width: NumberDraft;
  gen_height: NumberDraft;
  out_width: NumberDraft;
  out_height: NumberDraft;
  fps: NumberDraft;
  /** Whether the story gets planned music (MUSIC-006). */
  music_enabled: boolean;
};

export const NUMBER_FIELDS = ["gen_width", "gen_height", "out_width", "out_height", "fps"] as const;

export function initialDraft(project: ProjectDetail): Draft {
  return {
    name: project.name,
    gen_width: project.gen_width,
    gen_height: project.gen_height,
    out_width: project.out_width,
    out_height: project.out_height,
    fps: project.fps,
    music_enabled: project.music_enabled,
  };
}

/**
 * Only the fields that differ from the saved project. An emptied number box is
 * sent as null, so the server's own "cannot be empty" message is what shows.
 */
export function changedFields(project: ProjectDetail, draft: Draft): ProjectUpdate {
  const saved = initialDraft(project);
  const changes: ProjectUpdate = {};

  if (draft.name !== saved.name) {
    changes.name = draft.name;
  }
  if (draft.music_enabled !== saved.music_enabled) {
    changes.music_enabled = draft.music_enabled;
  }
  for (const field of NUMBER_FIELDS) {
    if (draft[field] !== saved[field]) {
      changes[field] = draft[field] === "" ? null : Number(draft[field]);
    }
  }
  return changes;
}

/** A key that changes whenever the saved settings do, so the form restarts from them. */
export function settingsKey(project: ProjectDetail): string {
  return JSON.stringify(initialDraft(project));
}
