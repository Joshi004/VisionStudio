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
  useGenerationRequests,
  usePlanAllRequests,
  usePlanOneShotRequest,
  usePlanSceneRequests,
  type GenerationRequestEntry,
  type RequestAudio,
  type RequestPicture,
  type SceneGenerationRequests,
} from "../../api/generationRequests";
import { PromptHoverCard } from "./PromptHoverCard";

type GenerationRequestsPanelProps = {
  projectId: number;
};

const STATUS: Record<
  GenerationRequestEntry["status"],
  { label: string; color: string }
> = {
  not_planned: { label: "Not planned", color: "gray" },
  planned: { label: "Planned", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

const ROUTE_LABELS: Record<string, string> = {
  reference: "Reference clip (pictures and speech)",
  text: "Text clip (no pictures)",
  first_frame: "Continuation clip (first frame, no other pictures)",
};

function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

function seconds(value: number): string {
  return `${value.toFixed(2)} s`;
}

/** What a picture is, in a few words: whose, which angle, which look or state. */
function pictureLabel(picture: RequestPicture): string {
  if (picture.kind === "anchor") {
    return picture.subject_name;
  }
  const view = picture.kind === "environment" ? "place" : humanize(picture.view);
  const variant =
    picture.variant === "default" ? "" : `, ${humanize(picture.variant)}`;
  return `${picture.subject_name}: ${view}${variant}`;
}

/** One picture of the request. A character is shown at 2:3 and a place at 16:9. */
function Thumbnail({ picture }: { picture: RequestPicture }) {
  const environment = picture.kind === "environment";
  if (picture.kind === "anchor") {
    // The last frame of the shot before: it is cut from that shot's selected take when this
    // shot is generated, so there is no picture to show yet.
    return (
      <Stack gap={2} w={160}>
        <Text size="xs" c="dimmed">
          Cut from the selected take when the shot is generated.
        </Text>
        <Text size="xs" style={{ wordBreak: "break-word" }}>
          &lt;{picture.label}&gt; {pictureLabel(picture)}
        </Text>
      </Stack>
    );
  }
  return (
    <Stack gap={2} w={environment ? 160 : 90}>
      {picture.url !== null ? (
        <PromptHoverCard imageId={picture.lab_image_id} block>
          <img
            src={picture.url}
            alt={pictureLabel(picture)}
            loading="lazy"
            style={{
              width: "100%",
              aspectRatio: environment ? "16 / 9" : "2 / 3",
              objectFit: "cover",
              borderRadius: 4,
              display: "block",
              background: "var(--mantine-color-gray-1)",
            }}
          />
        </PromptHoverCard>
      ) : (
        <Text size="xs" c="red">
          The picture no longer exists.
        </Text>
      )}
      <Text size="xs" style={{ wordBreak: "break-word" }}>
        &lt;{picture.label}&gt; {pictureLabel(picture)}
      </Text>
    </Stack>
  );
}

/** One dialogue audio of the request: who says it, when it starts, and a player. */
function AudioRow({ audio }: { audio: RequestAudio }) {
  return (
    <Stack gap={2}>
      <Group gap="xs">
        <Badge variant="light" color="gray" style={{ textTransform: "none" }}>
          &lt;{audio.label}&gt;
        </Badge>
        <Text size="sm">
          {audio.speaker_id}: &ldquo;{audio.text}&rdquo;
        </Text>
        {!audio.speaker_visible && (
          <Badge variant="light" color="grape">
            unseen speaker
          </Badge>
        )}
        <Badge variant="light" color="gray" style={{ textTransform: "none" }}>
          {audio.marker}
        </Badge>
      </Group>
      <Text size="xs" c="dimmed">
        Starts {seconds(audio.starts_in_shot_seconds)} into the shot, lasts{" "}
        {seconds(audio.duration_s)}.
      </Text>
      {audio.url !== null ? (
        <audio controls preload="none" src={audio.url} style={{ height: 32 }} />
      ) : (
        <Text size="xs" c="red">
          The speech file is no longer stored.
        </Text>
      )}
    </Stack>
  );
}

type ShotRowProps = {
  entry: GenerationRequestEntry;
  busy: boolean;
  onPlan: () => void;
};

/** One shot: its status, why it is out of date, and the request it is generated from. */
function ShotRow({ entry, busy, onPlan }: ShotRowProps) {
  const [open, setOpen] = useState(false);
  const { shot, request, version } = entry;
  const status = STATUS[entry.status];
  const planned = entry.status !== "not_planned";

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
            {version !== null && (
              <PromptHoverCard
                source={version.source}
                codeNote="Planned by code from the shot's references and speech. No model was asked."
              >
                <Badge variant="light" style={{ cursor: "help" }}>
                  v{version.version}
                </Badge>
              </PromptHoverCard>
            )}
            {request !== null && (
              <Badge variant="light" color="gray" style={{ textTransform: "none" }}>
                {request.target_seconds} s target, {request.num_frames} frames (
                {seconds(request.clip_seconds)}), {request.width}x
                {request.height}
              </Badge>
            )}
            <Text size="sm" style={{ wordBreak: "break-word" }}>
              {shot.description}
            </Text>
          </Group>
          {request !== null && (
            <Text size="xs" c="dimmed">
              {ROUTE_LABELS[request.route] ?? request.route}: {request.endpoint}
              ; {request.pictures.length}{" "}
              {request.pictures.length === 1 ? "picture" : "pictures"},{" "}
              {request.audios.length}{" "}
              {request.audios.length === 1 ? "audio" : "audios"}
            </Text>
          )}
          {request?.anchor != null && (
            <Text size="xs" c="dimmed">
              Continues {request.anchor.from_shot_id}: the last frame of its
              selected take is{" "}
              {request.anchor.use === "first_frame"
                ? "this clip's first frame"
                : `one more reference picture (Picture ${request.anchor.picture_order})`}
              .
            </Text>
          )}
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
          {request?.notes.map((text) => (
            <Text key={text} size="xs" c="dimmed">
              {text}
            </Text>
          ))}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {request !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the request" : "Show the request"}
            </Button>
          )}
          <Button
            size="compact-xs"
            variant="default"
            disabled={!entry.can_run || busy || entry.status === "planned"}
            onClick={onPlan}
          >
            {planned ? "Plan again" : "Plan"}
          </Button>
        </Group>
      </Group>
      {request !== null && (
        <Collapse expanded={open}>
          <Stack gap="sm" pt={4}>
            {request.pictures.length > 0 && (
              <Group gap="md" align="flex-start">
                {request.pictures.map((picture) => (
                  <Thumbnail key={picture.order} picture={picture} />
                ))}
              </Group>
            )}
            {request.audios.map((audio) => (
              <AudioRow key={audio.order} audio={audio} />
            ))}
          </Stack>
        </Collapse>
      )}
    </Stack>
  );
}

type SceneRowProps = {
  scene: SceneGenerationRequests;
  busy: boolean;
  onPlanScene: () => void;
  onPlanShot: (shotId: string) => void;
};

/** One scene: how many of its shots have a request, and its shots. */
function SceneRow({ scene, busy, onPlanScene, onPlanShot }: SceneRowProps) {
  const planned = scene.shots.filter((shot) => shot.status === "planned").length;
  const outOfDate = scene.shots.filter(
    (shot) => shot.status === "out_of_date",
  ).length;
  // What "Plan scene" would do for this scene.
  const todo = scene.shots.filter(
    (shot) => shot.can_run && shot.status !== "planned",
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
            {planned} of {scene.shots.length} planned
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
          onClick={onPlanScene}
          style={{ flexShrink: 0 }}
        >
          Plan scene
        </Button>
      </Group>
      {scene.shots.length > 0 && (
        <Stack gap="sm" ml={48}>
          {scene.shots.map((entry) => (
            <ShotRow
              key={entry.shot.id}
              entry={entry}
              busy={busy}
              onPlan={() => onPlanShot(entry.shot.id)}
            />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

/**
 * The Generation planning stage: for each shot with its references chosen, the exact request the
 * video model will be asked for. Code works it out (no model): the route and endpoint, the frame
 * count on H3's grid at or above the shot's length, the size from the project's orientation, the
 * pictures in order and the dialogue speech to copy. Narration is never sent. A shot's request is
 * planned by itself when its references are chosen.
 */
export function GenerationRequestsPanel({
  projectId,
}: GenerationRequestsPanelProps) {
  const { data, isLoading, isError, error } = useGenerationRequests(projectId);
  const planAll = usePlanAllRequests(projectId);
  const planScene = usePlanSceneRequests(projectId);
  const planOne = usePlanOneShotRequest(projectId);

  const entries = data?.entries ?? [];
  const busy = planAll.isPending || planScene.isPending || planOne.isPending;
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  // What "Plan all" would do: the shots that may be planned and have no current request.
  const allCount = entries.reduce(
    (sum, scene) =>
      sum +
      scene.shots.filter((shot) => shot.can_run && shot.status !== "planned")
        .length,
    0,
  );
  // The shots the last press could not do, with why.
  const skipped = [
    ...(planAll.data?.skipped ?? []),
    ...(planScene.data?.skipped ?? []),
    ...(planOne.data?.skipped ?? []),
  ].filter((item) => item.shot_id !== null);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Generation planning</Title>
            <Text size="sm" c="dimmed">
              Works out the exact request each shot is made from: the kind of
              clip, the number of frames (never shorter than the shot), the
              size, the reference pictures and the speech of the shot&apos;s
              dialogue. Narration is never sent. This is done by rule, not by a
              model, and by itself when a shot&apos;s references are chosen.
            </Text>
          </Stack>
          <Button
            onClick={() => planAll.mutate()}
            loading={planAll.isPending}
            disabled={
              isLoading || isError || busy || projectBlocked || allCount === 0
            }
            style={{ flexShrink: 0 }}
          >
            Plan all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the generation requests">
            {describeError(error)}
          </Alert>
        )}
        {[planAll, planScene, planOne].map(
          (mutation, position) =>
            mutation.isError && (
              <Alert
                key={position}
                color="red"
                title="Could not plan the requests"
              >
                {describeError(mutation.error)}
              </Alert>
            ),
        )}
        {skipped.some((item) => !item.reason.startsWith("Already")) && (
          <Alert color="blue" title="Not planned">
            <Stack gap={2}>
              {skipped
                .filter((item) => !item.reason.startsWith("Already"))
                .map((item) => (
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
            onPlanScene={() => planScene.mutate(scene.id)}
            onPlanShot={(shotId) =>
              planOne.mutate({ sceneId: scene.id, shotId })
            }
          />
        ))}
      </Stack>
    </Paper>
  );
}
