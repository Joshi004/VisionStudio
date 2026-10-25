import type {
  MusicPlanAnchor,
  MusicPlanAnchorInput,
  MusicPlanCue,
  MusicPlanTimeline,
} from "../../api/musicPlan";

/** Seconds as `m:ss`. */
export function formatSeconds(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export const KIND_LABELS: Record<string, string> = {
  score: "Score",
  bed: "Ambience bed",
  point: "Point sound",
  hit: "Hit",
  silence: "Silence",
};

export const MAKER_LABELS: Record<string, string> = {
  ace_step: "ACE-Step",
  stable_audio_3: "Stable Audio 3",
  h3: "H3",
};

export const JOIN_LABELS: Record<string, string> = {
  crossfade: "crossfade",
  under_cover: "under cover",
  through_silence: "through silence",
  hard_cut: "hard cut",
};

export const START_STYLE_LABELS: Record<string, string> = {
  fade_in: "fade in",
  hard_start: "hard start",
  rise_from_ambience: "rise out of the ambience",
};

export const END_STYLE_LABELS: Record<string, string> = {
  fade_out: "fade out",
  hard_stop: "hard stop",
  musical_ending: "musical ending",
  sting: "sting",
};

export const RELATION_LABELS: Record<string, string> = {
  before: "before",
  just_before: "just before",
  on: "on",
  after: "after",
  under: "under",
};

/** Colours of the strip, by kind of cue (Mantine colour names). */
export const KIND_COLORS: Record<string, string> = {
  score: "blue",
  bed: "teal",
  point: "orange",
  hit: "red",
  silence: "gray",
};

/** A short readable name for a reference of the timeline (`unit:s1/su_2`, `shot:...`). */
export function refLabel(timeline: MusicPlanTimeline, ref: string): string {
  const scene = timeline.scenes.find((item) => item.ref === ref);
  if (scene) return `scene "${scene.title}"`;
  const unit = timeline.units.find((item) => item.ref === ref);
  if (unit) {
    const who = unit.speaker ? `${unit.speaker}: ` : "";
    return `line ${who}"${shorten(unit.text, 50)}"`;
  }
  const shot = timeline.shots.find((item) => item.ref === ref);
  if (shot) return `${shot.ref.split(":")[1]} (${shorten(shot.description, 40)})`;
  const event = timeline.events.find((item) => item.ref === ref);
  if (event) {
    return `${event.type.replace("_", " ")} ${event.ref.split(":")[1]}${
      event.description ? ` (${shorten(event.description, 40)})` : ""
    }`;
  }
  return ref;
}

export function shorten(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

/** The nominal second of an anchor against a timeline, as the server works it out, or null. */
export function anchorSeconds(
  timeline: MusicPlanTimeline,
  anchor: Pick<MusicPlanAnchorInput, "ref" | "edge" | "relation">,
): number | null {
  const span =
    timeline.scenes.find((item) => item.ref === anchor.ref) ??
    timeline.shots.find((item) => item.ref === anchor.ref) ??
    timeline.units.find((item) => item.ref === anchor.ref) ??
    timeline.events.find((item) => item.ref === anchor.ref);
  if (!span) return null;
  if (anchor.relation === "under") return (span.start_s + span.end_s) / 2;
  return anchor.edge === "start" ? span.start_s : span.end_s;
}

/** "under line "Arjun?" (1:02)" for the plan text. */
export function describeAnchor(timeline: MusicPlanTimeline, anchor: MusicPlanAnchor): string {
  const relation = RELATION_LABELS[anchor.relation] ?? anchor.relation;
  const edge = anchor.relation === "under" ? "" : ` the ${anchor.edge} of`;
  return `${relation}${edge} ${refLabel(timeline, anchor.ref)}`;
}

/** The first and last second a cue covers. A point sound or hit has one moment. */
export function cueSpan(cue: MusicPlanCue): { start: number; end: number } {
  const start = (cue.start ?? cue.at)?.seconds ?? 0;
  const end = (cue.end ?? cue.at)?.seconds ?? start;
  return { start, end };
}

/** The cue as one line of the plan: where it sits in time. */
export function cueTimes(cue: MusicPlanCue): string {
  const { start, end } = cueSpan(cue);
  return cue.at ? formatSeconds(start) : `${formatSeconds(start)} to ${formatSeconds(end)}`;
}
