import type { JobSummary } from "../../api/jobs";

const TYPE_LABELS: Record<JobSummary["type"], string> = {
  lab_video: "Video lab clip",
  write_lab_video_prompt: "Video lab prompt",
  lab_voice: "Voice lab speech",
  lab_music: "Music lab sound",
  write_lab_music_prompt: "Music lab prompt",
  lab_image: "Image lab image",
  write_character_look_prompt: "Character look prompt",
  write_character_take_prompt: "Character take prompts",
  write_story_bible: "Story Bible",
  discover_characters: "Character discovery",
  discover_environments: "Environment discovery",
  discover_scenes: "Scene discovery",
  define_character: "Character definition",
  discover_relations: "Character relations",
  design_voice: "Voice design",
  write_environment_prompt: "Environment reference prompt",
  define_environment: "Environment definition",
  define_scene: "Scene definition",
  extract_events: "Event extraction",
  resolve_looks_states: "Look and state resolution",
  synthesize_speech_unit: "Speech unit audio",
  plan_shots: "Shot planning",
  define_shot: "Shot definition",
  check_shot_continuity: "Shot continuity check",
  repair_shot_cut: "Cut repair",
  compile_shot_prompt: "Shot prompt",
  generate_shot: "Shot clip",
  render_story: "Story video",
  check_shot_takes: "Take check",
  story_pipeline: "Story pipeline",
  check_take_dialogue: "Dialogue check",
  select_shot_references: "Shot references",
};

export function jobTypeLabel(type: JobSummary["type"]): string {
  return TYPE_LABELS[type];
}

/** The Lab tab a job that belongs to no project is shown in. */
export function labPathFor(type: JobSummary["type"]): string {
  switch (type) {
    case "lab_image":
      return "/lab/image";
    case "lab_voice":
      return "/lab/voice";
    case "lab_music":
    case "write_lab_music_prompt":
      return "/lab/music";
    case "write_character_look_prompt":
    case "write_character_take_prompt":
      return "/lab/characters";
    case "write_environment_prompt":
      return "/lab/environments";
    default:
      return "/lab/video";
  }
}

const STATUS_COLORS: Record<JobSummary["status"], string> = {
  queued: "gray",
  running: "blue",
  succeeded: "green",
  failed: "red",
  cancelled: "gray",
};

export function statusColor(status: JobSummary["status"]): string {
  return STATUS_COLORS[status];
}

/** "40 s", "1 min 20 s", "1 h 5 min". */
export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) {
    return `${seconds} s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = seconds % 60;
    return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
  }
  const hours = Math.floor(minutes / 60);
  const minutesRest = minutes % 60;
  return minutesRest === 0 ? `${hours} h` : `${hours} h ${minutesRest} min`;
}

/** A rough length of time: rounded to the minute from two minutes up, so it does not look exact. */
function roughElapsed(seconds: number): string {
  return formatElapsed(seconds < 120 ? seconds : Math.round(seconds / 60) * 60);
}

/** "typically about 12 min", from the server's usual run time. Empty when it is not known. */
export function typicalText(typicalSeconds: number | null): string {
  if (typicalSeconds === null || typicalSeconds <= 0) {
    return "";
  }
  return `typically about ${roughElapsed(typicalSeconds)}`;
}

/**
 * What the GPU server said about a job when it took it: "4 GPUs, about 12 min to run". The
 * estimate leaves out the wait in the server's own queue. Null when the server said neither,
 * so the caller can say it is still waiting for the answer.
 */
export function serverEstimateText(
  gpus: number | null,
  estimatedRunSeconds: number | null,
): string | null {
  const parts: string[] = [];
  if (gpus !== null) {
    parts.push(`${gpus} GPUs`);
  }
  if (estimatedRunSeconds !== null && estimatedRunSeconds > 0) {
    parts.push(`about ${roughElapsed(estimatedRunSeconds)} to run`);
  }
  return parts.length === 0 ? null : parts.join(", ");
}

type Timed = Pick<
  JobSummary,
  "status" | "created_at" | "started_at" | "finished_at"
>;

/**
 * How long a job has waited, run or taken, worked out from the stored times and `now`
 * (milliseconds since 1970). It is computed when the page renders, so it is right whenever
 * you look. A page that shows a running job passes a `now` from `useNow`, which ticks once a
 * second (ANALYSIS.md Section 3.4).
 */
export function elapsedText(job: Timed, now: number): string {
  const created = Date.parse(job.created_at);
  const started = job.started_at ? Date.parse(job.started_at) : created;
  const finished = job.finished_at ? Date.parse(job.finished_at) : null;

  if (job.status === "queued") {
    return `waiting ${formatElapsed((now - created) / 1000)}`;
  }
  if (job.status === "running") {
    return `running ${formatElapsed((now - started) / 1000)}`;
  }
  if (finished === null) {
    return "";
  }
  const verb = job.status === "cancelled" ? "cancelled after" : "took";
  return `${verb} ${formatElapsed((finished - created) / 1000)}`;
}

/** Only a job that has not finished shows its phase: for the others it repeats the status. */
export function showsPhase(status: JobSummary["status"]): boolean {
  return status === "queued" || status === "running";
}
