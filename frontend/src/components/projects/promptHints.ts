import type { MissingInput } from "../../api/sceneInputs";
import { H3_MODEL } from "../../videoModels";

/** ANALYSIS.md Section 5.4: "one flowing paragraph, about 200 words or fewer". */
export const MAX_DESCRIPTION_WORDS = 200;
/** The three fields of a MiniMax H3 description together (the backend profile's limit). */
export const MAX_H3_DESCRIPTION_WORDS = 260;

export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

// Straight and curly double quotes (LTX lip-syncs quoted speech).
const DOUBLE_QUOTES = /["\u201c\u201d\u201e]/;
const CUT_TO = /\bcut to\b/i;
// A transition named in words is a real edit for LTX-2.5 (same pattern as the backend profile).
const NAMED_CUT = /\b(hard|match|jump|smash) cut\b|\bcuts? away\b|\bcuts? (?:to|into)\b/i;
// "0:03", "3 seconds", "2.5 sec". Not a bare "s", so "the 1920s" does not match.
const TIMESTAMP = /\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?(sec|secs|second|seconds)\b/i;
const VIDEO_STARTS_WITH = /\bthe video (starts|begins) with\b/i;

// MiniMax H3 (the same patterns as the backend's `minimax-h3-scene` profile).
const H3_FIELDS = /integrated_multimodal_description\s*:/i;
const H3_FRAME_LINE = /For the target video,|How the reference pictures align/i;
const H3_NOT_SHOT_ONE = /integrated_multimodal_description\s*:(?!\s*\[Shot 1\])/i;
const H3_LATER_SHOT = /\[Shot\s+(?:[2-9]|\d{2,})\]/i;
const H3_SPEECH = /<\/?d>/i;
const H3_OWN_MUSIC = /non_diegetic_music\s*:(?!\s*N\/A\b)\s*\S/i;

/** Small warnings about a description written for MiniMax H3, which reads three fields. */
function h3Hints(description: string): string[] {
  if (!H3_FIELDS.test(description)) {
    return [
      "MiniMax H3 reads three fields: integrated_multimodal_description, overall_soundscape and non_diegetic_music. A plain description is wrapped in one shot, with a plain soundscape and no music, when the clip is made. Draft the descriptions again for MiniMax H3 to give it more to go on.",
    ];
  }
  const hints: string[] = [];
  const words = countWords(description);
  if (words > MAX_H3_DESCRIPTION_WORDS) {
    hints.push(
      `The description has ${words} words. About ${MAX_H3_DESCRIPTION_WORDS} or fewer works best.`,
    );
  }
  const frameLine = H3_FRAME_LINE.test(description);
  if (frameLine) {
    hints.push(
      "A line that places the pictures on the clip found. The app writes that line, with the clip's own length: leave it out.",
    );
  }
  if (H3_NOT_SHOT_ONE.test(description)) {
    hints.push("The description does not begin with \u201c[Shot 1]\u201d.");
  }
  if (H3_LATER_SHOT.test(description)) {
    hints.push(
      "A second shot found. The clip of a scene is one continuous shot: the app makes the cuts between scenes.",
    );
  } else if (NAMED_CUT.test(description)) {
    hints.push(
      "A cut found (\u201cthe camera cuts to\u201d). The clip of a scene is one continuous shot. Use a camera move to change the view.",
    );
  }
  if (H3_SPEECH.test(description)) {
    hints.push("Spoken words (<d> tags) found. Nobody on screen speaks: the voiceover is the narration.");
  }
  if (DOUBLE_QUOTES.test(description)) {
    hints.push("Double quotes found. Nobody speaks here and there is no on-screen text.");
  }
  if (!frameLine && TIMESTAMP.test(description)) {
    hints.push(
      "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. A single shot has no times, and the clip's length is set by the scene.",
    );
  }
  if (H3_OWN_MUSIC.test(description)) {
    hints.push(
      "The music field is not \u201cN/A\u201d. The video has a voiceover and no score of its own.",
    );
  }
  return hints;
}

/**
 * Small warnings about a description, from ANALYSIS.md Section 5.4 (and, for MiniMax H3, the
 * server's guide). They never block saving: they only point at wording that tends to pull the
 * result away from the first frame. `model` is the video model that will make the scene's clip.
 */
export function promptHints(description: string, model: string | undefined): string[] {
  if (model === H3_MODEL) {
    return h3Hints(description);
  }
  const hints: string[] = [];
  const words = countWords(description);
  if (words > MAX_DESCRIPTION_WORDS) {
    hints.push(
      `The description has ${words} words. About ${MAX_DESCRIPTION_WORDS} or fewer works best.`,
    );
  }
  if (DOUBLE_QUOTES.test(description)) {
    hints.push(
      "Double quotes found. The video model lip-syncs quoted speech, and there is no dialogue here. Remove them.",
    );
  }
  if (CUT_TO.test(description)) {
    hints.push(
      "\u201ccut to\u201d found. Describe one continuous shot instead.",
    );
  }
  if (!CUT_TO.test(description) && NAMED_CUT.test(description)) {
    hints.push(
      "A named cut (\u201chard cut\u201d, \u201cmatch cut\u201d, \u201ccuts away\u201d) found. LTX-2.5 treats it as a real edit, but a clip made from one first frame is one continuous shot. Try cuts in the Video lab.",
    );
  }
  if (TIMESTAMP.test(description)) {
    hints.push(
      "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. Leave timing out: the clip's length is set by the scene.",
    );
  }
  if (VIDEO_STARTS_WITH.test(description)) {
    hints.push(
      "\u201cthe video starts with\u201d found. The first frame already shows the start: describe the motion.",
    );
  }
  return hints;
}

const MISSING_LABELS: Record<MissingInput, string> = {
  description: "description",
  first_frame: "first frame",
};

/** "description", "first frame", "description and first frame". */
export function missingText(missing: MissingInput[]): string {
  const labels = missing.map((item) => MISSING_LABELS[item]);
  if (labels.length <= 1) {
    return labels.join("");
  }
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}
