import type { ProjectDetail, ProjectUpdate } from "../../api/projects";
import type { CalloutStyle } from "./calloutStyles";
import type { CaptionMode } from "./captionModes";

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
  /** How an explainer's captions are delivered: burned in, or a caption file (CAP-001). */
  caption_mode: CaptionMode;
  /** Whether an explainer's render draws callouts (EXPLAINER-007). */
  callouts: boolean;
  /** How callouts are drawn: simple boxes or motion graphics (CMO-002). */
  callout_style: CalloutStyle;
  /** The text that steers a continuous explainer's voice (FLOW-002). Empty means none. */
  presenter_delivery: string;
  /** How an explainer's presenter is placed and moves on camera. Empty means none. */
  presenter_staging: string;
  /** What an explainer's presenter wears. Empty means their usual outfit. */
  presenter_outfit: string;
  /** Or one of the presenter's saved outfits (a named look of the Character Lab). */
  presenter_named_look_id: number | null;
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
    caption_mode: project.caption_mode,
    callouts: project.callouts,
    callout_style: project.callout_style,
    presenter_delivery: project.presenter_delivery ?? "",
    presenter_staging: project.presenter_staging ?? "",
    presenter_outfit: project.presenter_outfit ?? "",
    presenter_named_look_id: project.presenter_named_look_id ?? null,
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
  if (draft.caption_mode !== saved.caption_mode) {
    changes.caption_mode = draft.caption_mode;
  }
  if (draft.callouts !== saved.callouts) {
    changes.callouts = draft.callouts;
  }
  if (draft.callout_style !== saved.callout_style) {
    changes.callout_style = draft.callout_style;
  }
  const delivery = draft.presenter_delivery.trim();
  if (delivery !== saved.presenter_delivery.trim()) {
    // An emptied box clears the text, so the Story Bible's style or the default is used.
    changes.presenter_delivery = delivery === "" ? null : delivery;
  }
  const staging = draft.presenter_staging.trim();
  if (staging !== saved.presenter_staging.trim()) {
    // An emptied box clears the text, so the presenter stands.
    changes.presenter_staging = staging === "" ? null : staging;
  }
  const outfit = draft.presenter_outfit.trim();
  if (outfit !== saved.presenter_outfit.trim()) {
    // An emptied box clears the text, so the presenter wears their usual outfit.
    changes.presenter_outfit = outfit === "" ? null : outfit;
  }
  if (draft.presenter_named_look_id !== saved.presenter_named_look_id) {
    // Cleared when the default or a described outfit is chosen instead.
    changes.presenter_named_look_id = draft.presenter_named_look_id;
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
