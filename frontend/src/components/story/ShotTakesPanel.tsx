import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useGenerateAllShots,
  useGenerateOneShot,
  useGenerateSceneShots,
  useSelectTake,
  useShotTakes,
  type SceneShotTakes,
  type ShotTake,
  type ShotTakesEntry,
} from "../../api/shotTakes";
import { JobStatusBadge } from "../jobs/JobStatusBadge";

type ShotTakesPanelProps = {
  projectId: number;
};

const STATUS: Record<
  ShotTakesEntry["status"],
  { label: string; color: string }
> = {
  not_generated: { label: "Not generated", color: "gray" },
  generated: { label: "Generated", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

const TAKE_STATE: Record<ShotTake["state"], { label: string; color: string }> =
  {
    generating: { label: "Generating", color: "blue" },
    ready: { label: "Ready", color: "green" },
    failed: { label: "Failed", color: "red" },
  };

/** "2.33 s, 56 frames, 1344x768, with sound". */
function clipText(take: ShotTake): string {
  const parts: string[] = [];
  if (take.duration_s !== null) {
    parts.push(`${take.duration_s.toFixed(2)} s`);
  }
  if (take.frame_count !== null) {
    parts.push(`${take.frame_count} frames`);
  }
  if (take.width !== null && take.height !== null) {
    parts.push(`${take.width}x${take.height}`);
  }
  if (take.has_audio !== null) {
    parts.push(take.has_audio ? "with sound" : "no sound");
  }
  return parts.join(", ");
}

type TakeRowProps = {
  take: ShotTake;
  busy: boolean;
  onSelect: () => void;
};

/** One take: its number, state, what the clip measured, and a button to select it. */
function TakeRow({ take, busy, onSelect }: TakeRowProps) {
  const state = TAKE_STATE[take.state];
  return (
    <Stack gap={2}>
      <Group gap="xs" wrap="nowrap">
        <Badge variant="outline" color="gray">
          Take {take.take_number}
        </Badge>
        <Badge variant="light" color={state.color}>
          {state.label}
        </Badge>
        {take.selected && (
          <Badge variant="light" color="teal">
            Selected
          </Badge>
        )}
        <Text size="xs" c="dimmed" style={{ flexGrow: 1 }}>
          seed {take.seed}
          {take.state === "ready" ? `, ${clipText(take)}` : ""}
        </Text>
        {take.job !== null && take.job.status !== "succeeded" && (
          <JobStatusBadge job={take.job} />
        )}
        {take.state === "ready" && !take.selected && (
          <Button
            size="compact-xs"
            variant="default"
            disabled={busy}
            onClick={onSelect}
          >
            Select
          </Button>
        )}
      </Group>
      {take.reasons.map((text) => (
        <Text key={text} size="xs" c="yellow.8">
          {text}
        </Text>
      ))}
      {take.state === "failed" && take.job?.error && (
        <Text size="xs" c="red">
          {take.job.error}
        </Text>
      )}
    </Stack>
  );
}

type ShotRowProps = {
  entry: ShotTakesEntry;
  busy: boolean;
  onGenerate: () => void;
  onSelect: (takeId: number) => void;
};

/** One shot: its status, the selected clip, and its takes. */
function ShotRow({ entry, busy, onGenerate, onSelect }: ShotRowProps) {
  const [open, setOpen] = useState(false);
  const { shot, takes, job } = entry;
  const status = STATUS[entry.status];
  const selected = takes.find((take) => take.selected) ?? null;
  const hasTakes = takes.length > 0;
  const generating = takes.some((take) => take.state === "generating");

  return (
    <Stack gap={4}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={64}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {shot.id}
        </Badge>
        <Stack gap={2} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
            <Badge
              variant="light"
              color="gray"
              title="How long the shot lasts on the timeline"
            >
              {shot.duration_seconds} s target
            </Badge>
            {hasTakes && (
              <Badge variant="light" color="gray">
                {takes.length} {takes.length === 1 ? "take" : "takes"}
              </Badge>
            )}
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
            <Text size="sm" style={{ wordBreak: "break-word" }}>
              {shot.description}
            </Text>
          </Group>
          {!entry.can_run && entry.blocked_reason !== null && (
            <Text size="xs" c="dimmed">
              {entry.blocked_reason}
            </Text>
          )}
          {entry.reasons.map((text) => (
            <Text key={text} size="xs" c="yellow.8">
              {text}
            </Text>
          ))}
          {job?.status === "failed" && !generating && (
            <Alert color="red" p="xs" title="The last generation failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {hasTakes && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the takes" : "Show the takes"}
            </Button>
          )}
          <Button
            size="compact-xs"
            variant="default"
            disabled={!entry.can_run || busy}
            onClick={onGenerate}
          >
            {selected !== null ? "Regenerate" : "Generate"}
          </Button>
        </Group>
      </Group>
      {selected !== null && selected.url !== null && (
        <Stack gap={2} ml={72}>
          <video
            key={selected.id}
            src={selected.url}
            controls
            preload="metadata"
            style={{ maxWidth: 420, width: "100%" }}
          />
          <Text size="xs" c="dimmed">
            Take {selected.take_number}: {clipText(selected)}. The shot lasts{" "}
            {shot.duration_seconds} s; the clip is trimmed to that when the
            video is put together.
          </Text>
        </Stack>
      )}
      {hasTakes && (
        <Collapse expanded={open}>
          <Stack gap="xs" pt={4} ml={72}>
            {takes.map((take) => (
              <TakeRow
                key={take.id}
                take={take}
                busy={busy}
                onSelect={() => onSelect(take.id)}
              />
            ))}
          </Stack>
        </Collapse>
      )}
    </Stack>
  );
}

type SceneRowProps = {
  scene: SceneShotTakes;
  busy: boolean;
  onGenerateScene: () => void;
  onGenerateShot: (shotId: string) => void;
  onSelect: (shotId: string, takeId: number) => void;
};

/** One scene: how many of its shots have a clip, and its shots. */
function SceneRow({
  scene,
  busy,
  onGenerateScene,
  onGenerateShot,
  onSelect,
}: SceneRowProps) {
  const generated = scene.shots.filter(
    (shot) => shot.status === "generated",
  ).length;
  const outOfDate = scene.shots.filter(
    (shot) => shot.status === "out_of_date",
  ).length;
  // What "Generate scene" would do for this scene.
  const todo = scene.shots.filter(
    (shot) => shot.can_run && shot.status !== "generated",
  ).length;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={40}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {scene.index}
        </Badge>
        <Group gap="xs" style={{ flexGrow: 1 }}>
          <Text size="sm" fw={500}>
            {scene.title}
          </Text>
          <Badge variant="light" color="gray">
            {generated} of {scene.shots.length} generated
          </Badge>
          {outOfDate > 0 && (
            <Badge variant="light" color="yellow">
              {outOfDate} out of date
            </Badge>
          )}
        </Group>
        <Button
          size="compact-sm"
          variant="default"
          disabled={busy || todo === 0}
          onClick={onGenerateScene}
          style={{ flexShrink: 0 }}
        >
          Generate scene
        </Button>
      </Group>
      {scene.shots.length > 0 && (
        <Stack gap="sm" ml={48}>
          {scene.shots.map((entry) => (
            <ShotRow
              key={entry.shot.id}
              entry={entry}
              busy={busy}
              onGenerate={() => onGenerateShot(entry.shot.id)}
              onSelect={(takeId) => onSelect(entry.shot.id, takeId)}
            />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

/**
 * The shot generation stage: each shot's compiled prompt, pictures and dialogue audio are sent to
 * the video model, and the clip is stored as a take of the shot. Every press makes one more
 * take; the take that finished (or was selected) last is the selected one. Nothing starts by
 * itself: a clip holds 4 to 8 GPUs for minutes. Clips are not checked or retried yet.
 */
export function ShotTakesPanel({ projectId }: ShotTakesPanelProps) {
  const { data, isLoading, isError, error } = useShotTakes(projectId);
  const generateAll = useGenerateAllShots(projectId);
  const generateScene = useGenerateSceneShots(projectId);
  const generateOne = useGenerateOneShot(projectId);
  const selectTake = useSelectTake(projectId);

  const entries = data?.entries ?? [];
  const busy =
    generateAll.isPending ||
    generateScene.isPending ||
    generateOne.isPending ||
    selectTake.isPending;
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  // What "Generate all" would do: the shots that may be generated and have no current clip.
  const allCount = entries.reduce(
    (sum, scene) =>
      sum +
      scene.shots.filter((shot) => shot.can_run && shot.status !== "generated")
        .length,
    0,
  );
  // The shots the last press could not do, with why.
  const skipped = [
    ...(generateAll.data?.skipped ?? []),
    ...(generateScene.data?.skipped ?? []),
  ].filter(
    (item) => item.shot_id !== null && !item.reason.startsWith("Already"),
  );

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Shot generation</Title>
            <Text size="sm" c="dimmed">
              Sends each shot&apos;s prompt, pictures and dialogue speech to the
              video model and keeps the clip as a take of the shot. Shots run
              side by side when the GPU server has room. Each press adds a
              take, and the take that finished or was selected last is the one
              used. Nothing starts by itself, and clips are not checked yet.
            </Text>
          </Stack>
          <Button
            onClick={() => generateAll.mutate()}
            loading={generateAll.isPending}
            disabled={
              isLoading || isError || busy || projectBlocked || allCount === 0
            }
            style={{ flexShrink: 0 }}
          >
            Generate all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the shot clips">
            {describeError(error)}
          </Alert>
        )}
        {[generateAll, generateScene, generateOne, selectTake].map(
          (mutation, position) =>
            mutation.isError && (
              <Alert
                key={position}
                color="red"
                title="Could not generate the clips"
              >
                {describeError(mutation.error)}
              </Alert>
            ),
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not generated">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={`${item.scene_id}/${item.shot_id}`} size="sm">
                  {item.title}, {item.shot_id}: {item.reason}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        {data && data.blocked_reason !== null && (
          <Text size="sm" c="dimmed">
            {data.blocked_reason}
          </Text>
        )}
        {entries.length > 0 && <Divider />}

        {entries.map((scene) => (
          <SceneRow
            key={scene.id}
            scene={scene}
            busy={busy}
            onGenerateScene={() => generateScene.mutate(scene.id)}
            onGenerateShot={(shotId) =>
              generateOne.mutate({ sceneId: scene.id, shotId })
            }
            onSelect={(shotId, takeId) =>
              selectTake.mutate({ sceneId: scene.id, shotId, takeId })
            }
          />
        ))}
      </Stack>
    </Paper>
  );
}
