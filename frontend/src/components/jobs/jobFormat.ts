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
  render_scene: "Scene video",
  check_shot_takes: "Take check",
  story_pipeline: "Story pipeline",
  check_take_dialogue: "Dialogue check",
  select_shot_references: "Shot references",
  stage_scene: "Scene staging",
  plan_environment_views: "Environment view plan",
  write_environment_view_prompt: "Environment view prompt",
  write_music_bible: "Music Bible",
  write_music_theme_prompt: "Music theme prompt",
  write_music_plan: "Music plan",
  write_music_cue: "Music cue detail",
  audit_music_cues: "Music prompt audit",
  rewrite_music_prompt: "Music prompt rewrite",
  place_music: "Music placement",
  preview_music_mix: "Music preview",
  time_speech_words: "Time speech words",
  write_callout_plan: "Callout plan",
  time_lab_speech_words: "Time test speech words",
  render_av_test: "Render audio video test",
  write_lab_graphic_brief: "Graphics lab brief",
  write_lab_graphic_template_spec: "Graphics lab template spec",
  write_lab_graphic_block_scene: "Graphics lab block scene",
  write_lab_graphic_component: "Graphics lab component",
  render_lab_graphic: "Graphics lab render",
  time_lab_graphic_words: "Graphics lab word timing",
  write_graphic_theme: "Graphics theme",
  write_callout_look: "Callout look",
  write_shot_graphic_brief: "Graphic brief",
  write_shot_graphic_component: "Graphic component",
  write_shot_graphic_scene: "Graphic block scene",
  render_shot_graphic: "Graphic render",
  describe_photo: "Photo description",
  write_thumbnail_concepts: "Thumbnail ideas",
};

export function jobTypeLabel(type: JobSummary["type"]): string {
  return TYPE_LABELS[type];
}

/** True when `value` is one of the job types (a stray value from the address is not). */
export function isJobType(value: string): value is JobSummary["type"] {
  return Object.hasOwn(TYPE_LABELS, value);
}

/** Every job type with its label, in the order of the labels, for a picker. */
export function jobTypeOptions(): { value: JobSummary["type"]; label: string }[] {
  return (Object.keys(TYPE_LABELS) as JobSummary["type"][])
    .map((type) => ({ value: type, label: TYPE_LABELS[type] }))
    .sort((a, b) => a.label.localeCompare(b.label));
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
    case "describe_photo":
    case "time_lab_speech_words":
    case "render_av_test":
      return "/lab/characters";
    case "write_lab_graphic_brief":
    case "write_lab_graphic_template_spec":
    case "write_lab_graphic_block_scene":
    case "write_lab_graphic_component":
    case "render_lab_graphic":
    case "time_lab_graphic_words":
      return "/lab/graphics";
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

/** The five statuses a job is stored with, in the order it goes through them, with labels. */
export const JOB_STATUSES: { value: JobSummary["status"]; label: string }[] = [
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

/** True when `value` is one of the job statuses (a stray value from the address is not). */
export function isJobStatus(value: string): value is JobSummary["status"] {
  return JOB_STATUSES.some((status) => status.value === value);
}

export type JobStage = JobSummary["stage"];

const STAGE_LABELS: Record<JobStage, string> = {
  waiting: "Waiting",
  paused: "Paused",
  resubmitting: "Submitting again",
  starting: "Starting",
  waiting_to_upload: "Waiting to upload",
  uploading: "Uploading",
  waiting_for_gpu: "On server, waiting to start",
  running_on_server: "Running on server",
  fetching_result: "Fetching result",
  server_unreachable: "Server not answering",
  not_found: "Not found on server",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STAGE_COLORS: Record<JobStage, string> = {
  waiting: "gray",
  paused: "orange",
  resubmitting: "yellow",
  starting: "blue",
  waiting_to_upload: "gray",
  uploading: "cyan",
  waiting_for_gpu: "yellow",
  running_on_server: "blue",
  fetching_result: "teal",
  server_unreachable: "orange",
  not_found: "orange",
  running: "blue",
  completed: "green",
  failed: "red",
  cancelled: "gray",
};

export function stageLabel(stage: JobStage): string {
  return STAGE_LABELS[stage];
}

export function stageColor(stage: JobStage): string {
  return STAGE_COLORS[stage];
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
 * What the remote server said about a job when it took it: "about 12 min to run". The
 * estimate leaves out the wait in the server's own queue. Null when the server said nothing,
 * so the caller can say it is still waiting for the answer.
 */
export function serverEstimateText(estimatedRunSeconds: number | null): string | null {
  if (estimatedRunSeconds === null || estimatedRunSeconds <= 0) {
    return null;
  }
  return `about ${roughElapsed(estimatedRunSeconds)} to run`;
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

const QUEUE_STATE_LABELS: Record<string, string> = {
  scheduling: "being scheduled",
  model_limit: "model at its limit",
  gpu_limit: "all GPUs busy",
  priority: "behind more urgent work",
  slurm_pending: "waiting for the cluster",
  model_loading: "model loading",
};

/**
 * The GPU server's priority for a job and why it holds the job back: "Priority 3 · all GPUs
 * busy". Empty when the job has no priority on the server and no reason to show.
 */
export function priorityText(
  job: Pick<JobSummary, "server_priority" | "queue_state">,
): string {
  const parts: string[] = [];
  if (job.server_priority != null) {
    parts.push(`Priority ${job.server_priority}`);
  }
  if (job.queue_state != null) {
    parts.push(QUEUE_STATE_LABELS[job.queue_state] ?? job.queue_state);
  }
  return parts.join(" · ");
}

/** Only a job that has not finished shows its phase: for the others it repeats the status. */
export function showsPhase(status: JobSummary["status"]): boolean {
  return status === "queued" || status === "running";
}
