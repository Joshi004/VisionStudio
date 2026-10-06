/** "0:05" or "12:34" for a length in seconds. */
export function formatDuration(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const AUDIO_FORMAT_LABELS: Record<string, string> = {
  "audio/wav": "WAV",
  "audio/mpeg": "MP3",
  "audio/mp4": "M4A",
  "audio/flac": "FLAC",
};

export function audioFormatLabel(mime: string): string {
  return AUDIO_FORMAT_LABELS[mime] ?? mime;
}

export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
