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
  useRenderStory,
  useStoryRenders,
  type StoryRender,
} from "../../api/storyRenders";
import { formatBytes, formatDateTime } from "../../format";
import { JobStatusBadge } from "../jobs/JobStatusBadge";

type StoryRenderPanelProps = {
  projectId: number;
};

const STATUS: Record<
  StoryRender["status"],
  { label: string; color: string }
> = {
  current: { label: "Current", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

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

/** One render in the list: its status, why it is out of date, and what it was made from. */
function RenderRow({ render }: { render: StoryRender }) {
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
      {render.warnings.map((warning) => (
        <Text key={`${warning.shot_id}/${warning.code}`} size="xs" c="yellow.8">
          {warning.message}
        </Text>
      ))}
      <Stack gap={0} ml="md">
        {render.takes.map((take) => (
          <Text key={take.take_id} size="xs" c="dimmed">
            Scene {take.scene_index}, {take.shot_id}: take {take.take_number},{" "}
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
      </Stack>
    </Stack>
  );
}

/**
 * The final render stage: the selected clip of every shot is trimmed to its shot, put on one
 * timeline with the narration, and joined into one video. Nothing starts by itself: the owner
 * presses Render. The newest render is played here; the older ones are kept in the list.
 */
export function StoryRenderPanel({ projectId }: StoryRenderPanelProps) {
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
              lowered under it), and joins everything into one video. Nothing
              starts by itself. Music, subtitles and the final checks come
              later.
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
            {data.planned_frames} frames at {data.fps} fps).
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
                  <RenderRow key={item.id} render={item} />
                ))}
              </Stack>
            </Collapse>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
