import type { ScriptWord, Transcript } from "../../api/transcription";

/** The script's words in paragraphs, in order. */
export function groupByParagraph<T extends { paragraph: number }>(words: T[]): T[][] {
  const groups: T[][] = [];
  for (const word of words) {
    const last = groups[groups.length - 1];
    if (last && last[0].paragraph === word.paragraph) {
      last.push(word);
    } else {
      groups.push([word]);
    }
  }
  return groups;
}

/** What the browser shows when the pointer rests on a word. */
export function wordTitle(word: ScriptWord): string {
  const times = `${word.start.toFixed(2)} – ${word.end.toFixed(2)} s`;
  return word.matched ? times : `${times} (not heard, time estimated)`;
}

export function percent(part: number, whole: number): string {
  return whole === 0 ? "0%" : `${Math.round((part / whole) * 100)}%`;
}

const STALE_MESSAGES: Record<Transcript["stale_reasons"][number], string> = {
  script_changed: "The script has changed since this transcript was made.",
  voiceover_changed: "The voiceover has changed since this transcript was made.",
};

export function staleMessage(reason: Transcript["stale_reasons"][number]): string {
  return STALE_MESSAGES[reason];
}
