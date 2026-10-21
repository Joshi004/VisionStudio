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
import { isJobActive } from "../../api/polling";
import { useSceneEvents } from "../../api/sceneEvents";
import {
  useCheckAllContinuity,
  useCheckSceneContinuity,
  useRepairCut,
  useShotContinuity,
  type ContinuityMismatch,
  type SceneContinuity,
  type ShotContinuityFlag,
} from "../../api/shotContinuity";
import {
  useDefineAllShots,
  useDefineOneShot,
  useDefineSceneShots,
  useShotDefinitions,
  type SceneShotDefinitions,
  type ShotDefinitionEntry,
} from "../../api/shotDefinitions";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { ShotDefinitionView } from "./ShotDefinitionView";

type ShotDefinitionsPanelProps = {
  projectId: number;
};

const STATUS: Record<
  ShotDefinitionEntry["status"],
  { label: string; color: string }
> = {
  not_defined: { label: "Not defined", color: "gray" },
  defined: { label: "Defined", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

const CONTINUITY_STATUS: Record<
  SceneContinuity["status"],
  { label: string; color: string }
> = {
  not_checked: { label: "Continuity not checked", color: "gray" },
  checking: { label: "Checking continuity", color: "blue" },
  reconciling: { label: "Repairing cuts", color: "blue" },
  consistent: { label: "Continuity OK", color: "green" },
  mismatches: { label: "Continuity mismatch", color: "orange" },
};

/** A boundary's side as a person reads it: a shot's id, or the scene's start or end. */
function boundaryName(side: string): string {
  if (side === "scene_start") return "the scene's start";
  if (side === "scene_end") return "the scene's end";
  return `shot ${side}`;
}

type ShotRowProps = {
  entry: ShotDefinitionEntry;
  /** Where this shot's continuity stands; undefined until the continuity state has loaded. */
  continuity: ShotContinuityFlag | undefined;
  characterNames: Record<string, string>;
  /** True when the whole scene cannot be defined; the reason is shown once, on the scene. */
  sceneBlocked: boolean;
  busy: boolean;
  onDefine: () => void;
};

/** One shot: its status, why it is out of date, the job's failure, and its specification. */
function ShotRow({
  entry,
  continuity,
  characterNames,
  sceneBlocked,
  busy,
  onDefine,
}: ShotRowProps) {
  const [open, setOpen] = useState(false);
  const { shot, job } = entry;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
  const defined = entry.status !== "not_defined";
  const reason = sceneBlocked || active ? null : entry.blocked_reason;

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
            {entry.version !== null && (
              <Badge
                variant="light"
                title="The newest version of this shot's definition"
              >
                v{entry.version.version}
              </Badge>
            )}
            <Badge variant="light" color="gray">
              {shot.duration_seconds.toFixed(1)} s
            </Badge>
            {continuity?.redefined_round != null && (
              <Badge
                variant="light"
                color="grape"
                title="This version was written by a continuity repair, to line up with its neighbour"
                style={{ textTransform: "none" }}
              >
                Repaired for continuity
                {continuity.redefined_round > 0
                  ? ` (round ${continuity.redefined_round})`
                  : ""}
              </Badge>
            )}
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
            <Text size="sm" style={{ wordBreak: "break-word" }}>
              {shot.description}
            </Text>
          </Group>
          {reason !== null && (
            <Text size="xs" c="dimmed">
              {reason}
            </Text>
          )}
          {entry.reasons.map((text) => (
            <Text key={text} size="xs" c="yellow.8">
              {text}
            </Text>
          ))}
          {job?.status === "failed" && (
            <Alert color="red" p="xs" title="The last definition failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.definition !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the specification" : "Show the specification"}
            </Button>
          )}
          <Button
            size="compact-xs"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy}
            onClick={onDefine}
          >
            {defined ? "Define again" : "Define"}
          </Button>
        </Group>
      </Group>
      {entry.definition !== null && entry.version !== null && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title={`Specification of ${shot.id}`}
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <ShotDefinitionView
              definition={entry.definition}
              characterNames={characterNames}
            />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

type SceneRowProps = {
  scene: SceneShotDefinitions;
  /** The scene's continuity; undefined until the continuity state has loaded. */
  continuity: SceneContinuity | undefined;
  characterNames: Record<string, string>;
  projectBlocked: boolean;
  busy: boolean;
  onDefineScene: () => void;
  onDefineShot: (shotId: string) => void;
  onCheckContinuity: () => void;
  onRepairCut: (boundaryId: string) => void;
};

/** The continuity of one scene: its status and the button. The cuts that fail are shown between the shots. */
function ContinuityLine({
  continuity,
  busy,
  onCheck,
}: {
  continuity: SceneContinuity;
  busy: boolean;
  onCheck: () => void;
}) {
  const status = CONTINUITY_STATUS[continuity.status];
  const running =
    continuity.status === "checking" || continuity.status === "reconciling";
  const label =
    continuity.status === "reconciling"
      ? `Repairing cuts (round ${continuity.round} of ${continuity.max_rounds})`
      : continuity.status === "mismatches"
        ? `${continuity.mismatches.length} ${
            continuity.mismatches.length === 1 ? "mismatch" : "mismatches"
          }`
        : status.label;
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Badge variant="light" color={status.color}>
          {label}
        </Badge>
        {continuity.status === "mismatches" &&
          continuity.round_limit_reached && (
            <Text size="xs" c="dimmed">
              The {continuity.max_rounds} automatic rounds are used.
            </Text>
          )}
        {continuity.job?.status === "failed" && !running && (
          <Text size="xs" c="red">
            The last check failed: {continuity.job.error ?? "the job failed."}
          </Text>
        )}
        <Button
          size="compact-xs"
          variant="default"
          loading={running}
          disabled={!continuity.can_run || busy}
          onClick={onCheck}
        >
          Check continuity
        </Button>
      </Group>
      {!continuity.can_run && !running && continuity.blocked_reason && (
        <Text size="xs" c="dimmed">
          {continuity.blocked_reason}
        </Text>
      )}
    </Stack>
  );
}

type CutRowProps = {
  mismatch: ContinuityMismatch;
  busy: boolean;
  onRepair: () => void;
};

/**
 * A cut that does not line up, shown where the cut is: between the two shots (or before the
 * first shot, or after the last one, for the scene's start and end). The problem belongs to
 * the cut, so it is repaired from here.
 */
function CutRow({ mismatch, busy, onRepair }: CutRowProps) {
  const { job } = mismatch;
  const active = isJobActive(job);
  return (
    <Alert
      color="orange"
      p="xs"
      title={`Does not line up: ${boundaryName(mismatch.before)} to ${boundaryName(mismatch.after)}`}
    >
      <Stack gap={4}>
        <Text size="sm" style={{ wordBreak: "break-word" }}>
          {mismatch.problem}
        </Text>
        {job?.status === "failed" && (
          <Text size="xs" c="red">
            The last repair failed: {job.error ?? "the job failed."}
          </Text>
        )}
        {!mismatch.can_repair && !active && mismatch.blocked_reason && (
          <Text size="xs" c="dimmed">
            {mismatch.blocked_reason}
          </Text>
        )}
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="default"
            loading={active}
            disabled={!mismatch.can_repair || busy}
            onClick={onRepair}
          >
            Fix this cut
          </Button>
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
        </Group>
      </Stack>
    </Alert>
  );
}

/** One scene: how many of its shots are defined, why they cannot be, and its shots. */
function SceneRow({
  scene,
  continuity,
  characterNames,
  projectBlocked,
  busy,
  onDefineScene,
  onDefineShot,
  onCheckContinuity,
  onRepairCut,
}: SceneRowProps) {
  const defined = scene.shots.filter(
    (shot) => shot.status === "defined",
  ).length;
  const outOfDate = scene.shots.filter(
    (shot) => shot.status === "out_of_date",
  ).length;
  const active = scene.shots.some((shot) => isJobActive(shot.job));
  const reason = projectBlocked ? null : scene.blocked_reason;
  // What "Define shots" would start for this scene.
  const todo = scene.shots.filter(
    (shot) => shot.can_run && shot.status !== "defined",
  ).length;
  // The cuts that do not line up, each shown at its place: the start of the scene before the
  // first shot, every other cut after the shot it follows (the scene's end after the last).
  const mismatches = continuity?.mismatches ?? [];
  const cutRow = (item: ContinuityMismatch) => (
    <CutRow
      key={item.id}
      mismatch={item}
      busy={busy}
      onRepair={() => onRepairCut(item.id)}
    />
  );

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
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {scene.title}
            </Text>
            {scene.plan_version !== null ? (
              <Badge
                variant="light"
                color="gray"
                title="The version of the scene's shot plan the shots are read from"
              >
                {defined} of {scene.shots.length} defined
              </Badge>
            ) : (
              <Badge variant="light" color="gray">
                Shots not planned
              </Badge>
            )}
            {outOfDate > 0 && (
              <Badge variant="light" color="yellow">
                {outOfDate} out of date
              </Badge>
            )}
          </Group>
          {reason !== null && (
            <Text size="xs" c="dimmed">
              {reason}
            </Text>
          )}
          {continuity !== undefined && scene.shots.length > 0 && (
            <ContinuityLine
              continuity={continuity}
              busy={busy}
              onCheck={onCheckContinuity}
            />
          )}
        </Stack>
        <Button
          size="compact-sm"
          variant="default"
          loading={active}
          disabled={!scene.can_run || busy || todo === 0}
          onClick={onDefineScene}
          style={{ flexShrink: 0 }}
        >
          Define shots
        </Button>
      </Group>
      {scene.shots.length > 0 && (
        <Stack gap="sm" ml={48}>
          {mismatches
            .filter((item) => item.before === "scene_start")
            .map(cutRow)}
          {scene.shots.map((entry) => (
            <Stack key={entry.shot.id} gap="sm">
              <ShotRow
                entry={entry}
                continuity={continuity?.shots.find(
                  (flag) => flag.shot_id === entry.shot.id,
                )}
                characterNames={characterNames}
                sceneBlocked={scene.blocked_reason !== null}
                busy={busy}
                onDefine={() => onDefineShot(entry.shot.id)}
              />
              {mismatches
                .filter((item) => item.before === entry.shot.id)
                .map(cutRow)}
            </Stack>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

/**
 * The Shot Definition stage: one model call per shot turns its skeleton into a full cinematic
 * specification. A scene's shots can only be defined once its shot plan is current and ready
 * for generation and the looks and states are resolved. **Define all** covers every such shot
 * whose definition is missing or out of date.
 */
export function ShotDefinitionsPanel({ projectId }: ShotDefinitionsPanelProps) {
  const { data, isLoading, isError, error } = useShotDefinitions(projectId);
  const defineAll = useDefineAllShots(projectId);
  const defineScene = useDefineSceneShots(projectId);
  const defineOne = useDefineOneShot(projectId);
  const checkAll = useCheckAllContinuity(projectId);
  const checkScene = useCheckSceneContinuity(projectId);
  const repairCut = useRepairCut(projectId);
  // Characters are shown by name; the event list already carries them for its own panel.
  const sceneEvents = useSceneEvents(projectId).data;

  const entries = data?.entries ?? [];
  // A check follows the last shot of a scene to be defined, so the continuity is asked again
  // while any shot is being defined.
  const definitionsActive = entries.some((scene) =>
    scene.shots.some((shot) => isJobActive(shot.job)),
  );
  const continuity = useShotContinuity(projectId, definitionsActive).data;
  const continuityByScene = new Map(
    (continuity?.entries ?? []).map((scene) => [scene.id, scene]),
  );
  const busy =
    defineAll.isPending ||
    defineScene.isPending ||
    defineOne.isPending ||
    checkAll.isPending ||
    checkScene.isPending ||
    repairCut.isPending;
  // What "Check all continuity" would start: scenes that can be checked and are not consistent.
  const checkAllCount = (continuity?.entries ?? []).filter(
    (scene) => scene.can_run && scene.status !== "consistent",
  ).length;
  const checkSkipped = checkAll.data?.skipped ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  const characterNames = Object.fromEntries(
    (sceneEvents?.characters ?? []).map((character) => [
      character.id,
      character.name,
    ]),
  );
  // What "Define all" would start: the shots of scenes that may run and are not defined and current.
  const allCount = entries.reduce(
    (sum, scene) =>
      sum +
      scene.shots.filter((shot) => shot.can_run && shot.status !== "defined")
        .length,
    0,
  );
  const skipped = [
    ...(defineAll.data?.skipped ?? []),
    ...(defineScene.data?.skipped ?? []),
  ].filter((item) => item.shot_id === null);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Shot definitions</Title>
            <Text size="sm" c="dimmed">
              Describes each planned shot in detail: what is visible and how the
              characters look, stand and gaze, the framing and camera, the
              action, where it starts and ends, and the ambience and sounds. The
              length and the dialogue come from the timeline, not from the
              model. A scene's shots can be defined once its timeline is ready
              for generation and its looks and states are resolved. Once every
              shot of a scene is defined, the scene's continuity is checked:
              where each shot ends must be where the next one starts. Shots that
              do not line up are shown at the cut between the two shots. The
              repair sees both shots and changes the one that needs it, a few
              rounds at most; a cut can also be fixed by hand.
            </Text>
          </Stack>
          <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
            <Button
              variant="default"
              onClick={() => checkAll.mutate()}
              loading={checkAll.isPending}
              disabled={
                isLoading ||
                isError ||
                busy ||
                projectBlocked ||
                checkAllCount === 0
              }
            >
              Check all continuity
            </Button>
            <Button
              onClick={() => defineAll.mutate()}
              loading={defineAll.isPending}
              disabled={
                isLoading || isError || busy || projectBlocked || allCount === 0
              }
            >
              Define all
            </Button>
          </Group>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the shot definitions">
            {describeError(error)}
          </Alert>
        )}
        {[defineAll, defineScene, defineOne].map(
          (mutation, position) =>
            mutation.isError && (
              <Alert
                key={position}
                color="red"
                title="Could not start the shot definition"
              >
                {describeError(mutation.error)}
              </Alert>
            ),
        )}
        {[checkAll, checkScene, repairCut].map(
          (mutation, position) =>
            mutation.isError && (
              <Alert
                key={position}
                color="red"
                title="Could not start the continuity check or repair"
              >
                {describeError(mutation.error)}
              </Alert>
            ),
        )}
        {checkSkipped.length > 0 && (
          <Alert color="blue" title="Continuity not checked">
            <Stack gap={2}>
              {checkSkipped.map((item) => (
                <Text key={item.scene_id} size="sm">
                  {item.title}: {item.reason}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not started">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={item.scene_id} size="sm">
                  {item.title}: {item.reason}
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
            continuity={continuityByScene.get(scene.id)}
            characterNames={characterNames}
            projectBlocked={projectBlocked}
            busy={busy}
            onDefineScene={() => defineScene.mutate(scene.id)}
            onDefineShot={(shotId) =>
              defineOne.mutate({ sceneId: scene.id, shotId })
            }
            onCheckContinuity={() => checkScene.mutate(scene.id)}
            onRepairCut={(boundaryId) =>
              repairCut.mutate({ sceneId: scene.id, boundaryId })
            }
          />
        ))}
      </Stack>
    </Paper>
  );
}
