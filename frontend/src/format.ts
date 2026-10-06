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

/** A time from the API (ISO 8601) in the browser's local time. */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

/** "sha256:00197efee9fe…": enough to tell two versions apart. Show the full value in a title. */
export function shortFingerprint(fingerprint: string): string {
  return fingerprint.length > 20 ? `${fingerprint.slice(0, 19)}…` : fingerprint;
}
