import { Alert, Badge, Button, Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";

import { useCopyAvTest, useRenderAvTest, type AvSegment, type AvTest } from "../../api/avLab";
import { describeError } from "../../api/errors";
import type { JobSummary } from "../../api/jobs";
import { formatDateTime } from "../../format";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { AvMarkedText } from "./AvMarkedText";
import {
  AV_MARKER_LABELS,
  AV_STATUS_BADGES,
  otherMarker,
  secondsText,
} from "./avLabView";
import { ORIENTATION_LABELS } from "./characterLabView";

const SEGMENT_BADGES: Record<AvSegment["status"], { label: string; color: string }> = {
  waiting: { label: "waiting", color: "gray" },
  working: { label: "working", color: "blue" },
  ready: { label: "ready", color: "green" },
  failed: { label: "failed", color: "red" },
};

const VIDEO_STYLE = { width: "100%", maxHeight: 460, background: "#000" } as const;

function JobLine({ label, job, now }: { label: string; job: JobSummary | null; now: number }) {
  if (job === null) {
    return null;
  }
  return (
    <Group gap="xs" wrap="nowrap" justify="space-between" align="flex-start">
      <Group gap="xs" wrap="wrap">
        <Text size="sm" fw={500} w={140}>
          {label}
        </Text>
        <JobStatusBadge job={job} />
        <Text size="xs" c="dimmed">
          {elapsedText(job, now)}
        </Text>
      </Group>
      <JobActions job={job} />
    </Group>
  );
}

function Segment({ segment }: { segment: AvSegment }) {
  const badge = SEGMENT_BADGES[segment.status];
  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group gap="xs" wrap="wrap">
          <Badge variant="light" color={badge.color}>
            {badge.label}
          </Badge>
          <Text size="sm" fw={600}>
            Part {segment.position}
          </Text>
          <Text size="xs" c="dimmed">
            {secondsText(segment.start_s)} to {secondsText(segment.end_s)} of the speech · clip of{" "}
            {segment.clip_frames} frames ({secondsText(segment.clip_frames / 24)})
            {segment.step !== null ? ` · ${segment.step} running` : ""}
          </Text>
        </Group>
        <Text size="sm">{segment.text}</Text>
        {segment.error !== null && (
          <Alert color="red" p="xs" title="This clip stopped">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {segment.error}
            </Text>
          </Alert>
        )}
        {segment.audio_url !== null && (
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              The part of the speech the clip hears
            </Text>
            <audio src={segment.audio_url} controls preload="metadata" style={{ width: "100%" }} />
          </Stack>
        )}
        {segment.clip_url !== null && (
          <Stack gap={2}>
            <video
              src={segment.clip_url}
              controls
              preload="metadata"
              playsInline
              style={{ ...VIDEO_STYLE, maxHeight: 320 }}
            />
            <Text size="xs" c="dimmed">
              Clip
              {segment.clip_duration_s !== null ? `, ${secondsText(segment.clip_duration_s)}` : ""}
              {segment.clip_has_sound === false ? " · no sound track" : ""}
            </Text>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

function Outputs({ test }: { test: AvTest }) {
  if (test.mixed_url === null || test.tts_only_url === null) {
    return null;
  }
  return (
    <Stack gap="xs">
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            Mixed
          </Text>
          <Text size="xs" c="dimmed">
            The speech in the gaps, and each clip&apos;s own sound inside its part.
          </Text>
          <video
            key={test.mixed_url}
            src={test.mixed_url}
            controls
            preload="metadata"
            playsInline
            style={VIDEO_STYLE}
          />
        </Stack>
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            Speech only
          </Text>
          <Text size="xs" c="dimmed">
            The clips are muted. The speech plays from the start to the end.
          </Text>
          <video
            key={test.tts_only_url}
            src={test.tts_only_url}
            controls
            preload="metadata"
            playsInline
            style={VIDEO_STYLE}
          />
        </Stack>
      </SimpleGrid>
      {test.render !== null && (
        <Text size="xs" c="dimmed">
          {test.render.frames} frames at {test.render.fps} fps ({secondsText(test.render.duration_s)}),{" "}
          {test.render.width} x {test.render.height}. Both videos have the same picture.
          {test.render.clips_without_sound.length > 0
            ? ` The clip of part ${test.render.clips_without_sound.join(", ")} has no sound track, so the mixed video is silent there.`
            : ""}
        </Text>
      )}
    </Stack>
  );
}

/**
 * One Audio video test: its text with the marked parts, the speech, the clip of each part, and
 * the two videos once rendered (the mixed one beside the speech-only one). "Copy with the other
 * mode" makes the same test again on the same speech with the other way of using it.
 */
export function AvTestCard({ test, now }: { test: AvTest; now: number }) {
  const render = useRenderAvTest();
  const copy = useCopyAvTest();
  const badge = AV_STATUS_BADGES[test.status];
  const other = otherMarker(test.audio_marker);
  const canCopy = test.timing !== null && test.segments.length > 0;
  const rendered = test.mixed_url !== null && test.tts_only_url !== null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <Badge variant="light" color={badge.color}>
                {badge.label}
              </Badge>
              <Text size="sm" fw={600}>
                Test {test.id} · {AV_MARKER_LABELS[test.audio_marker]} ·{" "}
                {ORIENTATION_LABELS[test.orientation]}
              </Text>
            </Group>
            <Text size="xs" c="dimmed">
              {formatDateTime(test.created_at)}
              {test.copied_from_id !== null ? ` · copied from test ${test.copied_from_id}` : ""}
            </Text>
          </Stack>
          {canCopy && (
            <Button
              size="compact-sm"
              variant="default"
              loading={copy.isPending}
              title="Makes a new test on the same speech, word times, parts and first frame, with the other way of using the speech. Each clip is a paid video run."
              onClick={() => copy.mutate({ testId: test.id, audioMarker: other })}
            >
              Copy with {AV_MARKER_LABELS[other].toLowerCase()}
            </Button>
          )}
        </Group>
        {copy.isError && (
          <Alert color="red" p="xs" title="The test was not copied">
            {describeError(copy.error)}
          </Alert>
        )}

        <AvMarkedText text={test.text} parts={test.parts} />
        <Text size="xs" c="dimmed">
          Spoken: {test.instruction}
        </Text>

        <Stack gap={4}>
          <JobLine label="Speech" job={test.speech_job} now={now} />
          <JobLine label="Word times" job={test.timing_job} now={now} />
          <JobLine label="Videos" job={test.render_job} now={now} />
        </Stack>

        {test.status === "failed" && test.error !== null && (
          <Alert color="red" p="xs" title="This test stopped">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {test.error}
            </Text>
          </Alert>
        )}
        {test.timing_warning !== null && (
          <Alert color="orange" p="xs">
            {test.timing_warning}
          </Alert>
        )}

        {test.speech_url !== null && (
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              The whole speech
              {test.speech_duration_s !== null ? `, ${secondsText(test.speech_duration_s)}` : ""}
              {test.timing !== null
                ? ` · words ${test.timing.source === "parakeet" ? "heard" : "estimated"} (${test.timing.match_percent}% matched)`
                : ""}
            </Text>
            <audio src={test.speech_url} controls preload="metadata" style={{ width: "100%" }} />
          </Stack>
        )}

        {test.segments.length > 0 && (
          <Stack gap="xs">
            {test.segments.map((segment) => (
              <Segment key={segment.position} segment={segment} />
            ))}
          </Stack>
        )}

        {(test.can_render || test.status === "rendering") && (
          <Group gap="sm" align="center">
            <Button
              size="compact-sm"
              loading={render.isPending || test.status === "rendering"}
              disabled={!test.can_render}
              onClick={() => render.mutate(test.id)}
            >
              {rendered ? "Render again" : "Render the two videos"}
            </Button>
            <Text size="xs" c="dimmed">
              Nothing is paid for: the videos are made on this machine.
            </Text>
          </Group>
        )}
        {render.isError && (
          <Alert color="red" p="xs" title="The videos were not started">
            {describeError(render.error)}
          </Alert>
        )}

        <Outputs test={test} />
      </Stack>
    </Paper>
  );
}
