import type { MissingInput } from "../../api/sceneInputs";

/** ANALYSIS.md Section 5.4: "one flowing paragraph, about 200 words or fewer". */
export const MAX_DESCRIPTION_WORDS = 200;

export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

// Straight and curly double quotes (LTX lip-syncs quoted speech).
const DOUBLE_QUOTES = /["\u201c\u201d\u201e]/;
const CUT_TO = /\bcut to\b/i;
// "0:03", "3 seconds", "2.5 sec". Not a bare "s", so "the 1920s" does not match.
const TIMESTAMP = /\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?(sec|secs|second|seconds)\b/i;
const VIDEO_STARTS_WITH = /\bthe video (starts|begins) with\b/i;

/**
 * Small warnings about a description, from ANALYSIS.md Section 5.4. They never block saving:
 * they only point at wording that tends to pull the result away from the two frames.
 */
export function promptHints(description: string): string[] {
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
      "\u201ccut to\u201d found. Describe one continuous motion between the two frames instead.",
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
  last_frame: "last frame",
};

/** "description", "description and last frame", "description, first frame and last frame". */
export function missingText(missing: MissingInput[]): string {
  const labels = missing.map((item) => MISSING_LABELS[item]);
  if (labels.length <= 1) {
    return labels.join("");
  }
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}
