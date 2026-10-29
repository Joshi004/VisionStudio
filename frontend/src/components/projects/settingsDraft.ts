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
  /** Whether a render includes the beds and the point sounds (MUSIC-012). */
  ambience_enabled: boolean;
  /** Whether an explainer's render draws word-synced captions (EXPLAINER-007). */
  captions: boolean;
  /** Whether an explainer's render draws callouts (EXPLAINER-007). */
  callouts: boolean;
  /** The text that steers a continuous explainer's voice (FLOW-002). Empty means none. */
  presenter_delivery: string;
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
    ambience_enabled: project.ambience_enabled,
    captions: project.captions,
    callouts: project.callouts,
    presenter_delivery: project.presenter_delivery ?? "",
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
  if (draft.ambience_enabled !== saved.ambience_enabled) {
    changes.ambience_enabled = draft.ambience_enabled;
  }
  if (draft.captions !== saved.captions) {
    changes.captions = draft.captions;
  }
  if (draft.callouts !== saved.callouts) {
    changes.callouts = draft.callouts;
  }
  const delivery = draft.presenter_delivery.trim();
  if (delivery !== saved.presenter_delivery.trim()) {
    // An emptied box clears the text, so the Story Bible's style or the default is used.
    changes.presenter_delivery = delivery === "" ? null : delivery;
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
