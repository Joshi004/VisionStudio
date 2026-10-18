import { H3_MODEL, type LabVideoModel } from "../../videoModels";

/** What the server's guide says one shot needs to register. */
export const SECONDS_PER_SHOT = 3;
/** The server's guide: about 200 words for one shot. No source gives a limit for a cut clip. */
export const MAX_PROMPT_WORDS = 200;
export const MIN_SHOTS = 2;
export const MAX_SHOTS = 4;
/** MiniMax H3 takes one to four shots (a single shot is right when interpolating two frames). */
export const H3_MIN_SHOTS = 1;
export const H3_MAX_SHOTS = 4;

function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

// A numbered or labelled shot list: "Shot 2:", "1.", "2)" at the start of a line.
const SHOT_LIST = /^\s*(?:shot\s*\d+\b|\d+\s*[.):])/im;
// A screenplay slugline: "INT. KITCHEN - DAY".
const SLUGLINE = /\b(?:INT|EXT)\.\s/;
// A cut named in words (the same pattern as the backend's `lab_prompt_writer`).
const TRANSITION =
  /\b(?:hard|match|jump|smash) cuts?\b|\bcuts? (?:away|to|into|back)\b|\b(?:dissolves?|fades?|wipes?|transitions?) (?:in)?to\b|\b(?:view|shot|image|camera|scene) (?:cuts|transitions|dissolves|jumps)\b/i;
const CUT_WORD = /\bcuts?\b/i;
const DOUBLE_QUOTES = /["\u201c\u201d\u201e]/;
// "0:03", "3 seconds", "2.5 sec". Not a bare "s", so "the 1920s" does not match.
const TIMESTAMP = /\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?(sec|secs|second|seconds)\b/i;

/** How many cuts the prompt names: the sentences that hold a named transition. */
export function countNamedCuts(text: string): number {
  return text.split(/(?<=[.!?])\s+/).filter((sentence) => TRANSITION.test(sentence)).length;
}

// The first field of a MiniMax H3 prompt for text and frames, and of its reference prompt.
const H3_FIELDS = /^\s*integrated_multimodal_description\s*:/im;
const H3_REFERENCE_FIELDS = /^\s*subject_definitions\s*:/im;

type HintInput = {
  prompt: string;
  durationS: number | null;
  models: LabVideoModel[];
  /** "h3_reference": a MiniMax H3 reference clip. Left out: one run per model. */
  kind?: "generate" | "h3_reference";
  /** How many reference pictures a reference clip has (`<Picture 1>` to `<Picture n>`). */
  pictureCount?: number;
  /** How many voices a reference clip has (`<Audio 1>` to `<Audio n>`), none being fine. */
  audioCount?: number;
};

/** Hints for the prompt of a MiniMax H3 reference clip: its six-part format and its labels. */
function referenceHints(text: string, pictureCount: number, audioCount: number): string[] {
  const hints: string[] = [];
  if (!H3_REFERENCE_FIELDS.test(text)) {
    hints.push(
      "MiniMax H3 reference mode was trained on six parts: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape and non_diegetic_music. Use the \u201cFill the prompt from the cast\u201d button, or write them.",
    );
  }
  for (let number = 1; number <= pictureCount; number += 1) {
    if (!text.includes(`<Picture ${number}>`)) {
      hints.push(`<Picture ${number}> is not named in the prompt. Say what it shows and how it is used.`);
    }
  }
  for (let number = 1; number <= audioCount; number += 1) {
    if (!text.includes(`<Audio ${number}>`)) {
      hints.push(
        `<Audio ${number}> is not named in the prompt. Say how the voice is used: reference (follow its voice and delivery), fully_copy, partially_copy or weak_reference.`,
      );
    }
  }
  if (audioCount === 0 && text.includes("<Audio")) {
    hints.push(
      "The prompt names an <Audio n> but no voice is chosen. Choose a voice for the character, or take the <Audio n> lines out.",
    );
  }
  return hints;
}

/**
 * Soft warnings about a prompt, from the server's guide and Lightricks' prompting guide for
 * LTX-2.5, and the server's guide for MiniMax H3's own structured prompt. They never block a
 * run: the lab exists to try exactly the wording that tends to go wrong, and to see what each
 * model does with it.
 */
export function labPromptHints({
  prompt,
  durationS,
  models,
  kind = "generate",
  pictureCount = 0,
  audioCount = 0,
}: HintInput): string[] {
  const text = prompt.trim();
  if (text === "") {
    return [];
  }
  if (kind === "h3_reference") {
    return referenceHints(text, pictureCount, audioCount);
  }
  const hints: string[] = [];
  const hasH3 = models.includes(H3_MODEL);
  const hasLtx = models.some((model) => model !== H3_MODEL);
  if (H3_FIELDS.test(text)) {
    // A MiniMax H3 prompt: [Shot N] blocks with cut times, which the LTX hints below would
    // misread (a time such as 00:03.000, a long prompt), so they are not applied to it.
    if (hasLtx) {
      hints.push(
        "This is a MiniMax H3 prompt, with its own fields and [Shot N] blocks. The LTX models read it as plain text, labels and brackets included, so an LTX prompt serves them better.",
      );
    }
    return hints;
  }
  if (hasH3) {
    hints.push(
      "MiniMax H3 was trained on a structured prompt (integrated_multimodal_description, overall_soundscape and non_diegetic_music). A plain prompt is accepted but gives it far less to go on: write the prompt with AI, in the MiniMax H3 format.",
    );
  }
  if (!hasLtx) {
    // The hints below are about LTX wording (named cuts, no times, about 200 words).
    return hints;
  }
  const cuts = countNamedCuts(text);
  const shots = cuts + 1;

  if (SHOT_LIST.test(text) || SLUGLINE.test(text)) {
    hints.push(
      "This looks like a shot list or a screenplay. LTX-2.5 reads one flowing paragraph and ignores labels such as \u201cShot 2:\u201d unless the cut is also written as a sentence.",
    );
  }
  if (cuts > MAX_SHOTS - 1) {
    hints.push(
      `${cuts} cuts are named. LTX-2.5 works best with ${MIN_SHOTS} to ${MAX_SHOTS} shots in one clip.`,
    );
  }
  if (cuts === 0 && CUT_WORD.test(text)) {
    hints.push(
      "The word \u201ccut\u201d is used, but no cut is named. Write the transition as a sentence: \u201cA hard cut transitions to a close-up of\u2026\u201d.",
    );
  }
  if (cuts > 0 && durationS !== null && durationS / shots < SECONDS_PER_SHOT) {
    hints.push(
      `${shots} shots in ${durationS} seconds is under ${SECONDS_PER_SHOT} seconds a shot. A shot needs about ${SECONDS_PER_SHOT} seconds to register: lengthen the clip, or use fewer shots.`,
    );
  }
  if (cuts > 0 && models.includes("ltx-2.3")) {
    hints.push(
      "LTX-2.3 makes one continuous shot, so it will not cut where the prompt names a cut. That is what the comparison shows.",
    );
  }
  if (DOUBLE_QUOTES.test(text)) {
    hints.push(
      "Double quotes found. Both models speak quoted words, with lip-sync. Remove them if nobody should speak.",
    );
  }
  if (TIMESTAMP.test(text)) {
    hints.push(
      "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. The models read no timings: the length is set by the form.",
    );
  }
  const words = countWords(text);
  if (words > MAX_PROMPT_WORDS) {
    hints.push(
      `The prompt has ${words} words. About ${MAX_PROMPT_WORDS} or fewer works best (the guide gives that figure for one shot).`,
    );
  }
  return hints;
}
