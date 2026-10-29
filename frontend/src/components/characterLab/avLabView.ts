import type { AvMarker, AvStatus, AvTestCreate } from "../../api/avLab";
import type { LibraryCharacter } from "../../api/characterLab";
import type { ReferenceItem } from "../imageLab/labView";

/** Same numbers as `services/av_lab.py` and `speech_synthesizer.py`. */
export const AV_TEXT_MAX_CHARS = 3000;
export const AV_INSTRUCTION_MAX_CHARS = 500;
export const AV_MAX_PARTS = 8;

export type AvOrientation = AvTestCreate["orientation"];

/** A part marked for video: the words from `start_word` to `end_word` (included), from 0. */
export type AvPart = { start_word: number; end_word: number };

export type AvFormState = {
  text: string;
  instruction: string;
  audioMarker: AvMarker;
  orientation: AvOrientation;
  firstFrame: ReferenceItem | null;
  parts: AvPart[];
};

export const DEFAULT_AV_FORM: AvFormState = {
  text: "",
  instruction: "",
  audioMarker: "fully_copy",
  orientation: "portrait",
  firstFrame: null,
  parts: [],
};

export const AV_MARKER_LABELS: Record<AvMarker, string> = {
  fully_copy: "Full copy",
  partially_copy: "Partial copy",
};

export const AV_MARKERS: readonly AvMarker[] = ["fully_copy", "partially_copy"];

/** The other way of using the speech: what "Copy with the other mode" asks for. */
export function otherMarker(marker: AvMarker): AvMarker {
  return marker === "fully_copy" ? "partially_copy" : "fully_copy";
}

export const AV_STATUS_BADGES: Record<AvStatus, { label: string; color: string }> = {
  speaking: { label: "making the speech", color: "blue" },
  timing: { label: "timing the words", color: "blue" },
  clips: { label: "making the clips", color: "blue" },
  ready: { label: "clips ready", color: "teal" },
  rendering: { label: "rendering", color: "blue" },
  done: { label: "done", color: "green" },
  failed: { label: "failed", color: "red" },
};

// --- The words of the text ---------------------------------------------------------------------

/** A word of the text and where it sits in it (character offsets, the end not included). */
export type TextWord = { text: string; start: number; end: number };

/**
 * The words of a text the way the server counts them (it splits at spaces and line breaks), so a
 * part's word numbers mean the same on both sides.
 */
export function wordsOf(text: string): TextWord[] {
  return Array.from(text.matchAll(/\S+/g), (match) => ({
    text: match[0],
    start: match.index,
    end: match.index + match[0].length,
  }));
}

/**
 * The words a selection of the text touches, from the first to the last, or null when it touches
 * none (an empty selection, or one inside the blanks between two words).
 */
export function partOfSelection(text: string, selectionStart: number, selectionEnd: number): AvPart | null {
  const words = wordsOf(text);
  const touched: number[] = [];
  words.forEach((word, index) => {
    if (word.start < selectionEnd && word.end > selectionStart) {
      touched.push(index);
    }
  });
  if (touched.length === 0) {
    return null;
  }
  return { start_word: touched[0], end_word: touched[touched.length - 1] };
}

/** The number (from 0) of the part that holds this word, or -1. */
export function partIndexOfWord(parts: readonly AvPart[], word: number): number {
  return parts.findIndex((part) => part.start_word <= word && word <= part.end_word);
}

/**
 * Adds a part, keeping the parts in order. Returns the new parts, or a reason it cannot be added
 * (too many parts, or it shares a word with one that is there).
 */
export function addPart(
  parts: readonly AvPart[],
  part: AvPart,
): { parts: AvPart[]; problem: null } | { parts: AvPart[]; problem: string } {
  if (parts.length >= AV_MAX_PARTS) {
    return { parts: [...parts], problem: `Mark at most ${AV_MAX_PARTS} parts: each one is a paid clip.` };
  }
  const overlaps = parts.some(
    (other) => part.start_word <= other.end_word && other.start_word <= part.end_word,
  );
  if (overlaps) {
    return { parts: [...parts], problem: "That selection touches a part that is already marked." };
  }
  const next = [...parts, part].sort((a, b) => a.start_word - b.start_word);
  return { parts: next, problem: null };
}

export function partText(text: string, part: AvPart): string {
  return wordsOf(text)
    .slice(part.start_word, part.end_word + 1)
    .map((word) => word.text)
    .join(" ");
}

// --- The form ----------------------------------------------------------------------------------

/** Why the form cannot be sent, or null when it can. */
export function avFormProblem(form: AvFormState, character: LibraryCharacter): string | null {
  if (character.voice === null) {
    return "This character has no voice. Give it one from Voice first.";
  }
  if (form.text.trim() === "") {
    return "Write the text to speak.";
  }
  if (form.text.trim().length > AV_TEXT_MAX_CHARS) {
    return `The text is longer than ${AV_TEXT_MAX_CHARS} characters.`;
  }
  if (form.instruction.trim() === "") {
    return "Write how the text is spoken: tone, emotion or pace.";
  }
  if (form.instruction.length > AV_INSTRUCTION_MAX_CHARS) {
    return `The instruction is longer than ${AV_INSTRUCTION_MAX_CHARS} characters.`;
  }
  if (form.firstFrame === null) {
    return "Choose the first frame: the picture the clips start from and the gaps show.";
  }
  if (form.parts.length === 0) {
    return "Select a part of the text and press Mark as video.";
  }
  return null;
}

export function toAvTestIn(form: AvFormState): AvTestCreate {
  const firstFrame = form.firstFrame as ReferenceItem;
  return {
    text: form.text.trim(),
    instruction: form.instruction.trim(),
    audio_marker: form.audioMarker,
    orientation: form.orientation,
    first_frame: { source: firstFrame.source, id: firstFrame.id },
    parts: form.parts,
  };
}

/** `5.2 s`: a length in seconds, rounded to a tenth. */
export function secondsText(seconds: number): string {
  return `${seconds.toFixed(1)} s`;
}
