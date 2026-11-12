// YouTube's limits for the draft, the same ones the backend checks
// (`services/youtube_draft_writer.py`). The panel uses them for the counters and to say, before
// anything is saved, why a draft cannot be kept.

export const TITLE_MAX_CHARS = 100;
export const DESCRIPTION_MAX_BYTES = 5000;
export const HASHTAGS_MAX = 5;
export const TAGS_MAX_CHARS = 500;
export const TAG_MAX_CHARS = 100;

const HASHTAG_PATTERN = /^[A-Za-z0-9_]+$/;
const encoder = new TextEncoder();

/** The title as it is saved: blank space collapsed and trimmed. */
export function normalizedTitle(title: string): string {
  return title.split(/\s+/).filter(Boolean).join(" ");
}

/** The description as it is saved: new lines as `\n`, trimmed. */
export function normalizedDescription(description: string): string {
  return description.replace(/\r\n/g, "\n").trim();
}

/** A hashtag as it is saved: trimmed, lowercase, without a leading `#` (the app adds it when sending). */
export function normalizedHashtag(tag: string): string {
  return tag.trim().replace(/^#/, "").toLowerCase();
}

/** The tags typed as comma-separated text: split on commas, blank space collapsed, empty pieces dropped. */
export function parseTags(text: string): string[] {
  return text
    .split(",")
    .map((piece) => piece.split(/\s+/).filter(Boolean).join(" "))
    .filter((tag) => tag !== "");
}

/**
 * The tags' length as YouTube counts it: every character, one comma between each two, and two
 * more for a tag that contains a space (it is counted as if in quotation marks).
 */
export function tagsLength(tags: string[]): number {
  const characters = tags.reduce((sum, tag) => sum + [...tag].length, 0);
  const quotes = tags.filter((tag) => tag.includes(" ")).length * 2;
  return characters + quotes + Math.max(tags.length - 1, 0);
}

/** The title's length in characters (code points, so an emoji counts once). */
export function titleLength(title: string): number {
  return [...normalizedTitle(title)].length;
}

/** The description as YouTube gets it: the text, an empty line, then `#one #two` on one line. */
export function descriptionWithHashtags(
  description: string,
  hashtags: string[],
): string {
  const text = normalizedDescription(description);
  if (hashtags.length === 0) {
    return text;
  }
  const line = hashtags.map((tag) => `#${tag}`).join(" ");
  return text === "" ? line : `${text}\n\n${line}`;
}

/** The size of the description with its hashtags, in UTF-8 bytes (YouTube allows 5,000). */
export function descriptionBytes(
  description: string,
  hashtags: string[],
): number {
  return encoder.encode(descriptionWithHashtags(description, hashtags)).length;
}

/** Why one hashtag cannot be kept, or null. */
export function hashtagProblem(tag: string): string | null {
  return HASHTAG_PATTERN.test(tag)
    ? null
    : `The hashtag "${tag}" must be one word of letters, digits or underscores, with no spaces.`;
}

/** Every reason the draft cannot be kept, one sentence each. Empty when it can. */
export function draftProblems(draft: {
  title: string;
  description: string;
  hashtags: string[];
  tags: string[];
}): string[] {
  const problems: string[] = [];
  const title = normalizedTitle(draft.title);
  if (title === "") {
    problems.push("The title is empty.");
  } else if (titleLength(title) > TITLE_MAX_CHARS) {
    problems.push(
      `The title is ${titleLength(title)} characters; YouTube allows at most ${TITLE_MAX_CHARS}.`,
    );
  }
  if (/[<>]/.test(title)) {
    problems.push("The title cannot hold the characters < or >.");
  }
  if (/[<>]/.test(draft.description)) {
    problems.push("The description cannot hold the characters < or >.");
  }
  for (const tag of draft.hashtags) {
    const problem = hashtagProblem(tag);
    if (problem !== null) {
      problems.push(problem);
    }
  }
  if (new Set(draft.hashtags.map((tag) => tag.toLowerCase())).size !== draft.hashtags.length) {
    problems.push("A hashtag appears more than once.");
  }
  if (draft.hashtags.length > HASHTAGS_MAX) {
    problems.push(`There can be at most ${HASHTAGS_MAX} hashtags.`);
  }
  for (const tag of draft.tags) {
    if (/[<>]/.test(tag)) {
      problems.push(`The tag "${tag}" cannot hold the characters < or >.`);
    }
    if ([...tag].length > TAG_MAX_CHARS) {
      problems.push(
        `The tag "${tag}" is ${[...tag].length} characters; the most allowed is ${TAG_MAX_CHARS}.`,
      );
    }
  }
  if (new Set(draft.tags.map((tag) => tag.toLowerCase())).size !== draft.tags.length) {
    problems.push("A tag appears more than once.");
  }
  const tagChars = tagsLength(draft.tags);
  if (tagChars > TAGS_MAX_CHARS) {
    problems.push(
      `The tags are ${tagChars} characters as YouTube counts them; the most allowed is ${TAGS_MAX_CHARS}.`,
    );
  }
  const bytes = descriptionBytes(draft.description, draft.hashtags);
  if (bytes > DESCRIPTION_MAX_BYTES) {
    problems.push(
      `The description with its hashtags is ${bytes.toLocaleString()} bytes; YouTube allows at most ${DESCRIPTION_MAX_BYTES.toLocaleString()}.`,
    );
  }
  return problems;
}
