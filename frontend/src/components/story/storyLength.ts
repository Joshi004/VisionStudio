const SECONDS_PER_MINUTE = 60;

/**
 * The number of words: runs of text between whitespace. It follows the backend's rule
 * (`count_words` in `backend/app/services/story_length.py`), so the two counts agree.
 */
export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

/**
 * The estimated length in whole seconds, from the words and the speaking pace. It follows the
 * backend's rule (`story_length` in `backend/app/services/story_length.py`): halves round up.
 */
export function estimateSeconds(words: number, wordsPerMinute: number): number {
  return Math.round((words * SECONDS_PER_MINUTE) / wordsPerMinute);
}

/** "32 s", "3 min" or "2 min 30 s". */
export function formatDuration(seconds: number): string {
  if (seconds < SECONDS_PER_MINUTE) {
    return `${seconds} s`;
  }
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  const rest = seconds % SECONDS_PER_MINUTE;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}
