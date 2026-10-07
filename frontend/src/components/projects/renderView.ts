import type { Render } from "../../api/renders";
import type { Scene } from "../../api/scenes";
import { formatBytes } from "../../format";

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/**
 * What the next render will use, in one line. The server decides which scenes block it
 * (`render_blocked_reason`); this only describes the render that is possible.
 */
export function renderSummary(
  scenes: Pick<Scene, "use_clip_sound">[],
  clipSoundVolume: number,
): string {
  const takes = scenes.length === 1 ? "the scene" : `each of the ${scenes.length} scenes`;
  const uses = `Uses the selected take of ${takes}, the voiceover at full level`;
  if (clipSoundVolume <= 0) {
    return `${uses}, and no clip sound (the project's clip sound volume is 0).`;
  }
  const muted = scenes.filter((scene) => !scene.use_clip_sound).length;
  const percent = Math.round(clipSoundVolume * 100);
  const mutedText = muted > 0 ? ` (${plural(muted, "scene")} muted)` : "";
  return `${uses}, and clip sound at ${percent}%${mutedText}.`;
}

/** "7 Oct, 08:40 · 14.2 s · 1080 x 1920 · clip sound 20% · 1 scene muted · 4.1 MB". */
export function renderLine(render: Render): string {
  const parts: string[] = [
    new Date(render.created_at).toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }),
  ];
  if (render.duration_s !== null) {
    parts.push(`${render.duration_s.toFixed(1)} s`);
  }
  if (render.width !== null && render.height !== null) {
    parts.push(`${render.width} x ${render.height}`);
  }
  if (render.clip_sound_volume !== null) {
    parts.push(
      render.clip_sound_volume > 0
        ? `clip sound ${Math.round(render.clip_sound_volume * 100)}%`
        : "no clip sound",
    );
  }
  if (render.muted_scene_count > 0) {
    parts.push(`${plural(render.muted_scene_count, "scene")} muted`);
  }
  parts.push(formatBytes(render.size_bytes));
  return parts.join(" · ");
}

/** "the-first-light-render-41.mp4": a file name for the Download button. */
export function downloadName(projectName: string, jobId: number): string {
  const slug = projectName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug === "" ? "video" : slug}-render-${jobId}.mp4`;
}
