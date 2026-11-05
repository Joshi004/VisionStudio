import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Collapse,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  captionFileUrl,
  useRenderStory,
  useStoryRenders,
  type StoryRender,
  type StoryRenders,
} from "../../api/storyRenders";
import { formatBytes, formatDateTime } from "../../format";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { SceneRenderList } from "./SceneRenderList";

type StoryRenderPanelProps = {
  projectId: number;
  /** Only an explainer has captions, so only it is told to render again for caption files. */
  isExplainer: boolean;
};

const STATUS: Record<
  StoryRender["status"],
  { label: string; color: string }
> = {
  current: { label: "Current", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

const GRAPHIC_ENGINE = {
  generated_component: "generated component",
  remotion_blocks: "building blocks",
} as const;

/** "9.50 s, 228 frames, 1280x720, 2.1 MB, with sound". */
function renderText(render: StoryRender): string {
  const parts: string[] = [];
  if (render.duration_s !== null) {
    parts.push(`${render.duration_s.toFixed(2)} s`);
  }
  if (render.frame_count !== null) {
    parts.push(`${render.frame_count} frames`);
  }
  if (render.width !== null && render.height !== null) {
    parts.push(`${render.width}x${render.height}`);
  }
  parts.push(formatBytes(render.size_bytes));
  parts.push(render.has_audio ? "with sound" : "no sound");
  return parts.join(", ");
}

/** "-28.8 LUFS, gain +6.0 dB". The level the source had and the change the render made. */
function levelText(loudness: number | null, gain: number | null): string {
  if (loudness === null || gain === null) {
    return "no sound";
  }
  const sign = gain > 0 ? "+" : "";
  return `${loudness.toFixed(1)} LUFS, gain ${sign}${gain.toFixed(1)} dB`;
}

/** "Music: placement version 2, 7 sounds (bed, score), ambience on." */
function musicText(music: NonNullable<StoryRender["music"]>): string {
  const parts = [
    `placement version ${music.placement_version}`,
    `${music.sounds} ${music.sounds === 1 ? "sound" : "sounds"} (${music.lanes.join(", ")})`,
  ];
  if (music.left_out > 0) {
    parts.push(`${music.left_out} left out`);
  }
  parts.push(music.ambience ? "ambience on" : "ambience off");
  return parts.join(", ");
}

/** "Finished sound: -14.1 LUFS, true peak -1.2 dBTP (target -14 LUFS, ceiling -1 dBTP)." */
function masterText(master: NonNullable<StoryRender["master"]>): string {
  const reached =
    master.final_lufs === null || master.final_true_peak_dbtp === null
      ? "not measured"
      : `${master.final_lufs.toFixed(1)} LUFS, true peak ${master.final_true_peak_dbtp.toFixed(1)} dBTP`;
  return `${reached} (target ${master.target_lufs} LUFS, ceiling ${master.true_peak_db} dBTP)`;
}

/**
 * The scenes of the newest render that differ from their newest scene render (SCN-013), and the
 * scenes that have no scene render at all (on one line). Music is not compared: a scene
 * render's music is cut to its window and may be provisional.
 */
function ChangedScenes({ scenes }: { scenes: StoryRenders["changed_scenes"] }) {
  const different = scenes.filter((scene) => scene.has_scene_render);
  const missing = scenes.filter((scene) => !scene.has_scene_render);
  if (scenes.length === 0) {
    return null;
  }
  return (
    <Stack gap={2}>
      {different.length > 0 && (
        <Text size="xs" fw={500}>
          Scenes that differ from their scene renders
        </Text>
      )}
      {different.map((scene) => (
        <Text key={scene.scene_id} size="xs" c="yellow.8">
          Scene {scene.scene_index}: {scene.title}. {scene.reasons.join(" ")}
        </Text>
      ))}
      {missing.length > 0 && (
        <Text size="xs" c="dimmed">
          No scene render: scene {missing.map((scene) => scene.scene_index).join(", ")}.
        </Text>
      )}
    </Stack>
  );
}

/**
 * The caption files of one render (CAP-002, CAP-003). A render with a caption track offers the
 * YouTube file and a plain SRT file, with a warning when the captions are also in the picture. An explainer's render with no
 * track (made before captions were always kept) is told to render again. A story has none.
 */
function CaptionFiles({
  render,
  projectId,
  isExplainer,
}: {
  render: StoryRender;
  projectId: number;
  isExplainer: boolean;
}) {
  if (!render.caption_file_available) {
    return isExplainer ? (
      <Text size="xs" c="dimmed">
        Render again to get caption files.
      </Text>
    ) : null;
  }
  return (
    <Stack gap={2}>
      <Group gap="xs">
        <Anchor
          href={captionFileUrl(projectId, render.render_number, "ytt")}
          download
          size="xs"
        >
          Download YouTube captions (YTT)
        </Anchor>
        <Anchor
          href={captionFileUrl(projectId, render.render_number, "srt")}
          download
          size="xs"
        >
          Download subtitles (SRT)
        </Anchor>
      </Group>
      {render.captions_burned && (
        <Text size="xs" c="yellow.8">
          This video already has captions in the picture. If you upload this
          file too, viewers who turn captions on will see them twice.
        </Text>
      )}
    </Stack>
  );
}

/** One render in the list: its status, why it is out of date, and what it was made from. */
function RenderRow({
  render,
  projectId,
  isExplainer,
}: {
  render: StoryRender;
  projectId: number;
  isExplainer: boolean;
}) {
  const status = STATUS[render.status];
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Badge variant="outline" color="gray">
          Render {render.render_number}
        </Badge>
        <Badge variant="light" color={status.color}>
          {status.label}
        </Badge>
        <Text size="xs" c="dimmed">
          {formatDateTime(render.created_at)}, {renderText(render)}
        </Text>
        <Anchor href={render.url} download size="xs">
          Download
        </Anchor>
      </Group>
      {render.reasons.map((text) => (
        <Text key={text} size="xs" c="yellow.8">
          {text}
        </Text>
      ))}
      <CaptionFiles
        render={render}
        projectId={projectId}
        isExplainer={isExplainer}
      />
      {render.warnings.map((warning) => (
        <Text key={`${warning.shot_id}/${warning.code}`} size="xs" c="yellow.8">
          {warning.message}
        </Text>
      ))}
      <Stack gap={0} ml="md">
        {render.takes.map((take) => (
          <Text key={`${take.scene_id}/${take.shot_id}`} size="xs" c="dimmed">
            Scene {take.scene_index}, {take.shot_id}:{" "}
            {take.graphic !== null
              ? `graphic (${GRAPHIC_ENGINE[take.graphic.engine]}, attempt ${take.graphic.attempt})`
              : `take ${take.take_number}`}
            ,{" "}
            {take.frames} frames, {levelText(take.loudness_lufs, take.gain_db)}
          </Text>
        ))}
        {render.narration !== null && (
          <Text size="xs" c="dimmed">
            Narration: {render.narration.units}{" "}
            {render.narration.units === 1 ? "line" : "lines"},{" "}
            {levelText(
              render.narration.loudness_lufs,
              render.narration.gain_db,
            )}
          </Text>
        )}
        {render.music !== null && (
          <Text size="xs" c="dimmed">
            Music: {musicText(render.music)}
          </Text>
        )}
        {render.master !== null && (
          <Text size="xs" c="dimmed">
            Finished sound: {masterText(render.master)}
          </Text>
        )}
      </Stack>
      {render.master?.notes.map((note) => (
        <Text key={note} size="xs" c="yellow.8">
          {note}
        </Text>
      ))}
    </Stack>
  );
}

/**
 * The final render stage: the selected clip of every shot is trimmed to its shot, put on one
 * timeline with the narration, and joined into one video. Nothing starts by itself: the owner
 * presses Render. The newest render is played here; the older ones are kept in the list.
 */
export function StoryRenderPanel({
  projectId,
  isExplainer,
}: StoryRenderPanelProps) {
  const { data, isLoading, isError, error } = useStoryRenders(projectId);
  const render = useRenderStory(projectId);
  const [showAll, setShowAll] = useState(false);

  const renders = data?.renders ?? [];
  const newest = renders[0] ?? null;
  const job = data?.job ?? null;
  const active = isJobActive(job);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Final render</Title>
            <Text size="sm" c="dimmed">
              Trims the selected clip of each shot to its length on the
              timeline, puts the narration on top (the clips&apos; own sound is
              lowered under it), mixes in the placed music and ambience, brings
              the finished sound to the target loudness, and joins everything
              into one video. Nothing starts by itself. An explainer&apos;s caption
              files can be downloaded from each render.
            </Text>
          </Stack>
          <Button
            onClick={() => render.mutate()}
            loading={render.isPending}
            disabled={isLoading || isError || !data?.can_render}
            style={{ flexShrink: 0 }}
          >
            {newest === null ? "Render" : "Render again"}
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the story video">
            {describeError(error)}
          </Alert>
        )}
        {render.isError && (
          <Alert color="red" title="Could not start the render">
            {describeError(render.error)}
          </Alert>
        )}
        {data && !data.can_render && data.blocked_reason !== null && (
          <Text size="sm" c="dimmed">
            {data.blocked_reason}
          </Text>
        )}
        {data && data.can_render && data.planned_seconds !== null && (
          <Text size="sm" c="dimmed">
            The video will be {data.planned_seconds.toFixed(2)} s (
            {data.planned_frames} frames at {data.fps} fps),{" "}
            {data.music_placement_version === null
              ? "without music."
              : `with the music of placement version ${data.music_placement_version}${
                  data.ambience_enabled ? "." : ", without ambience."
                }`}
          </Text>
        )}
        {data?.warnings.map((warning) => (
          <Text key={`${warning.shot_id}/${warning.code}`} size="sm" c="yellow.8">
            {warning.message}
          </Text>
        ))}

        {job !== null && job.status !== "succeeded" && (
          <Group gap="xs">
            <JobStatusBadge job={job} />
          </Group>
        )}
        {job?.status === "failed" && !active && (
          <Alert color="red" title="The last render failed">
            {job.error ?? "The job failed."}
          </Alert>
        )}

        {newest !== null && (
          <Stack gap={4}>
            <video
              key={newest.id}
              src={newest.url}
              controls
              preload="metadata"
              style={{ maxWidth: 640, width: "100%" }}
            />
            <Group gap="xs">
              <Badge variant="outline" color="gray">
                Render {newest.render_number}
              </Badge>
              <Badge variant="light" color={STATUS[newest.status].color}>
                {STATUS[newest.status].label}
              </Badge>
              <Text size="xs" c="dimmed">
                {renderText(newest)}
              </Text>
              <Anchor href={newest.url} download size="xs">
                Download
              </Anchor>
            </Group>
            {newest.reasons.map((text) => (
              <Text key={text} size="xs" c="yellow.8">
                {text}
              </Text>
            ))}
            <CaptionFiles
              render={newest}
              projectId={projectId}
              isExplainer={isExplainer}
            />
            {newest.master?.notes.map((note) => (
              <Text key={note} size="xs" c="yellow.8">
                {note}
              </Text>
            ))}
            <ChangedScenes scenes={data?.changed_scenes ?? []} />
          </Stack>
        )}

        {renders.length > 0 && (
          <Stack gap="xs">
            <Group>
              <Button
                size="compact-xs"
                variant="default"
                onClick={() => setShowAll((value) => !value)}
              >
                {showAll ? "Hide the renders" : "Show the renders"}
              </Button>
              <Text size="xs" c="dimmed">
                {renders.length} {renders.length === 1 ? "render" : "renders"}
              </Text>
            </Group>
            <Collapse expanded={showAll}>
              <Stack gap="sm" pt={4}>
                {renders.map((item) => (
                  <RenderRow
                    key={item.id}
                    render={item}
                    projectId={projectId}
                    isExplainer={isExplainer}
                  />
                ))}
              </Stack>
            </Collapse>
          </Stack>
        )}

        <SceneRenderList projectId={projectId} />
      </Stack>
    </Paper>
  );
}
