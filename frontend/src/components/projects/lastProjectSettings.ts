import { isCalloutStyle } from "./calloutStyles";
import type { CalloutStyle } from "./calloutStyles";
import { isCaptionMode } from "./captionModes";
import type { CaptionMode } from "./captionModes";
import { isOrientation } from "./orientations";
import type { Orientation } from "./orientations";
import { OUTFIT_MAX_CHARS, STAGING_MAX_CHARS, isProjectKind } from "./projectKinds";
import type { ProjectKind } from "./projectKinds";
import { isSpeechMode } from "./speechModes";
import type { SpeechMode } from "./speechModes";
import { isTakeSource } from "./takeSources";
import type { TakeSource } from "./takeSources";
import { DELIVERY_MAX_CHARS, isVoiceTrack } from "./voiceTracks";
import type { VoiceTrack } from "./voiceTracks";

/** Every setting of the New project form except the name, which is new for each project. */
export type NewProjectSettings = {
  orientation: Orientation | null;
  kind: ProjectKind;
  speechMode: SpeechMode;
  presenterId: string | null;
  setId: string | null;
  staging: string;
  outfitId: number | null;
  outfit: string;
  voiceTrack: VoiceTrack;
  takeSource: TakeSource;
  delivery: string;
  graphics: boolean;
  evidence: boolean;
  captionMode: CaptionMode;
  callouts: boolean;
  calloutStyle: CalloutStyle;
};

export const DEFAULT_SETTINGS: NewProjectSettings = {
  orientation: null,
  kind: "story",
  speechMode: "both",
  presenterId: null,
  setId: null,
  staging: "",
  outfitId: null,
  outfit: "",
  voiceTrack: "continuous",
  takeSource: "generated",
  delivery: "",
  graphics: true,
  evidence: true,
  captionMode: "burned",
  callouts: true,
  calloutStyle: "boxes",
};

const STORAGE_KEY = "visiostudio.newProject.lastSettings";

type StoredValues = Record<string, unknown>;

function isRecord(value: unknown): value is StoredValues {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A saved choice if it is still one of the allowed values, otherwise the default. */
function choice<T extends string>(
  value: unknown,
  isAllowed: (text: string) => text is T,
  fallback: T,
): T {
  return typeof value === "string" && isAllowed(value) ? value : fallback;
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function text(value: unknown, maxLength: number, fallback: string): string {
  return typeof value === "string" && value.length <= maxLength ? value : fallback;
}

/** The id of a library item, kept as the text the form's Select uses. */
function libraryId(value: unknown): string | null {
  return typeof value === "string" && /^[1-9]\d*$/.test(value) ? value : null;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

/**
 * What the browser remembers from the last project that was created. Each setting is checked on
 * its own: one that is missing or no longer valid falls back to its default, and anything
 * unexpected (bad JSON, no storage) gives the defaults.
 */
export function readLastSettings(): NewProjectSettings {
  let stored: unknown;
  try {
    stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
  } catch {
    return DEFAULT_SETTINGS;
  }
  if (!isRecord(stored)) {
    return DEFAULT_SETTINGS;
  }

  const defaults = DEFAULT_SETTINGS;
  const presenterId = libraryId(stored.presenterId);
  return {
    orientation:
      typeof stored.orientation === "string" && isOrientation(stored.orientation)
        ? stored.orientation
        : defaults.orientation,
    kind: choice(stored.kind, isProjectKind, defaults.kind),
    speechMode: choice(stored.speechMode, isSpeechMode, defaults.speechMode),
    presenterId,
    setId: libraryId(stored.setId),
    staging: text(stored.staging, STAGING_MAX_CHARS, defaults.staging),
    // A saved outfit belongs to the presenter, so it means nothing without one.
    outfitId: presenterId === null ? null : positiveInteger(stored.outfitId),
    outfit: text(stored.outfit, OUTFIT_MAX_CHARS, defaults.outfit),
    voiceTrack: choice(stored.voiceTrack, isVoiceTrack, defaults.voiceTrack),
    takeSource: choice(stored.takeSource, isTakeSource, defaults.takeSource),
    delivery: text(stored.delivery, DELIVERY_MAX_CHARS, defaults.delivery),
    graphics: flag(stored.graphics, defaults.graphics),
    evidence: flag(stored.evidence, defaults.evidence),
    captionMode: choice(stored.captionMode, isCaptionMode, defaults.captionMode),
    callouts: flag(stored.callouts, defaults.callouts),
    calloutStyle: choice(stored.calloutStyle, isCalloutStyle, defaults.calloutStyle),
  };
}

export function writeLastSettings(settings: NewProjectSettings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Private mode or a full quota: the project is still created, the settings are just not remembered.
  }
}

export function clearLastSettings() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear when storage is not available.
  }
}
