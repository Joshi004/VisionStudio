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
import { useSceneDefinitions } from "../../api/sceneDefinitions";
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
  useSaveShotDefinition,
  useShotDefinitions,
  type SceneShotDefinitions,
  type ShotDefinitionEntry,
  type ShotDefinitionInput,
} from "../../api/shotDefinitions";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { FeedbackBadge } from "./FeedbackBadge";
import { FeedbackModal } from "./FeedbackModal";
import { PromptHoverCard } from "./PromptHoverCard";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { ShotDefinitionEditor } from "./ShotDefinitionEditor";
import { ShotDefinitionView } from "./ShotDefinitionView";

type ShotDefinitionsPanelProps = {
  projectId: number;
};

/** What the user is asked to confirm: defining a shot again, or repairing a cut. */
type Confirming =
  | { kind: "define"; sceneId: string; shotId: string }
  | { kind: "repair"; sceneId: string; boundaryId: string; label: string };

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
  onFeedback: () => void;
  /** The ids of the scene's characters, for the editor's choices. */
  sceneCharacterIds: string[];
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (definition: ShotDefinitionInput, done: () => void) => void;
};

/**
 * One shot: its status, why it is out of date, the job's failure, and its specification, which
 * can be edited by hand.
 */
function ShotRow({
  entry,
  continuity,
  characterNames,
  sceneBlocked,
  busy,
  onDefine,
  onFeedback,
  sceneCharacterIds,
  saving,
  saveError,
  onStartEdit,
  onSave,
}: ShotRowProps) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
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
              <PromptHoverCard jobId={entry.version.job_id} source={entry.version.source}>
                <Badge variant="light" style={{ cursor: "help" }}>
                  v{entry.version.version}
                </Badge>
              </PromptHoverCard>
            )}
            <FeedbackBadge text={entry.version?.feedback} />
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
        <Group gap="xs" justify="flex-end" maw={420} style={{ flexShrink: 0 }}>
          {entry.definition !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the specification" : "Show the specification"}
            </Button>
          )}
          {entry.definition !== null && (
            <Button
              size="compact-xs"
              variant="default"
              disabled={editing || active || busy}
              onClick={() => {
                onStartEdit();
                setOpen(false);
                setEditing(true);
              }}
            >
              Edit
            </Button>
          )}
          <Button
            size="compact-xs"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy || editing}
            onClick={onDefine}
          >
            {defined ? "Define again" : "Define"}
          </Button>
          {entry.definition !== null && (
            <Button
              size="compact-xs"
              variant="default"
              title="Define this shot again, with a note from you for the model"
              disabled={!entry.can_run || busy || editing}
              onClick={onFeedback}
            >
              Regenerate with feedback
            </Button>
          )}
        </Group>
      </Group>
      {editing && entry.definition !== null && (
        <Paper withBorder p="md" radius="sm">
          <ShotDefinitionEditor
            initial={entry.definition}
            staging={entry.staging ?? null}
            sceneCharacterIds={sceneCharacterIds}
            characterNames={characterNames}
            saving={saving}
            error={saveError}
            onSave={(definition) => onSave(definition, () => setEditing(false))}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {entry.definition !== null && entry.version !== null && !editing && (
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
              staging={entry.staging ?? null}
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
  onFeedbackShot: (entry: ShotDefinitionEntry) => void;
  onCheckContinuity: () => void;
  onRepairCut: (mismatch: ContinuityMismatch) => void;
  sceneCharacterIds: string[];
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (
    shotId: string,
    definition: ShotDefinitionInput,
    done: () => void,
  ) => void;
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
  onFeedbackShot,
  onCheckContinuity,
  onRepairCut,
  sceneCharacterIds,
  saving,
  saveError,
  onStartEdit,
  onSave,
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
      onRepair={() => onRepairCut(item)}
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
                onFeedback={() => onFeedbackShot(entry)}
                sceneCharacterIds={sceneCharacterIds}
                saving={saving}
                saveError={saveError}
                onStartEdit={onStartEdit}
                onSave={(definition, done) =>
                  onSave(entry.shot.id, definition, done)
                }
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
  const save = useSaveShotDefinition(projectId);
  // Characters are shown by name; the event list already carries them for its own panel.
  const sceneEvents = useSceneEvents(projectId).data;
  // Which characters each scene has, for the editor's choices.
  const sceneDefinitions = useSceneDefinitions(projectId).data;
  // A shot or a cut waiting for "yes, write over what I wrote".
  const [confirming, setConfirming] = useState<Confirming | null>(null);
  // The shot the user is writing a note about.
  const [feedbackFor, setFeedbackFor] = useState<{
    sceneId: string;
    entry: ShotDefinitionEntry;
  } | null>(null);

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
  // A scene that was skipped, and a shot the user wrote (it is only redefined by its own
  // button). The other shot-level skips ("already defined") are not worth showing.
  const manualShots = new Set(
    entries.flatMap((scene) =>
      scene.shots
        .filter((shot) => shot.needs_confirmation)
        .map((shot) => `${scene.id}/${shot.shot.id}`),
    ),
  );
  const skipped = [
    ...(defineAll.data?.skipped ?? []),
    ...(defineScene.data?.skipped ?? []),
  ].filter(
    (item) =>
      item.shot_id === null || manualShots.has(`${item.scene_id}/${item.shot_id}`),
  );

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
                <Text key={`${item.scene_id}/${item.shot_id}`} size="sm">
                  {item.title}
                  {item.shot_id !== null ? `, ${item.shot_id}` : ""}:{" "}
                  {item.reason}
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
              scene.shots.find((shot) => shot.shot.id === shotId)
                ?.needs_confirmation
                ? setConfirming({ kind: "define", sceneId: scene.id, shotId })
                : defineOne.mutate({
                    sceneId: scene.id,
                    shotId,
                    confirmReplaceManual: false,
                  })
            }
            onFeedbackShot={(entry) =>
              setFeedbackFor({ sceneId: scene.id, entry })
            }
            onCheckContinuity={() => checkScene.mutate(scene.id)}
            onRepairCut={(mismatch) =>
              mismatch.needs_confirmation
                ? setConfirming({
                    kind: "repair",
                    sceneId: scene.id,
                    boundaryId: mismatch.id,
                    label: `${boundaryName(mismatch.before)} to ${boundaryName(mismatch.after)}`,
                  })
                : repairCut.mutate({
                    sceneId: scene.id,
                    boundaryId: mismatch.id,
                    confirmReplaceManual: false,
                  })
            }
            sceneCharacterIds={
              sceneDefinitions?.entries.find((item) => item.id === scene.id)
                ?.definition?.characters ?? []
            }
            saving={save.isPending}
            saveError={save.error}
            onStartEdit={() => save.reset()}
            onSave={(shotId, definition, done) =>
              save.mutate(
                { sceneId: scene.id, shotId, definition },
                { onSuccess: done },
              )
            }
          />
        ))}
      </Stack>
      <FeedbackModal
        opened={feedbackFor !== null}
        title={`Feedback on the definition of ${feedbackFor?.entry.shot.id ?? "this shot"}`}
        what="the definition of this shot"
        initialText={feedbackFor?.entry.version?.feedback ?? ""}
        writtenByUser={feedbackFor?.entry.needs_confirmation ?? false}
        submitLabel="Define with feedback"
        onCancel={() => setFeedbackFor(null)}
        onSubmit={(text) => {
          if (feedbackFor !== null) {
            defineOne.mutate({
              sceneId: feedbackFor.sceneId,
              shotId: feedbackFor.entry.shot.id,
              confirmReplaceManual: feedbackFor.entry.needs_confirmation,
              feedback: text,
            });
          }
          setFeedbackFor(null);
        }}
      />
      <ReplaceManualModal
        opened={confirming !== null}
        title={
          confirming?.kind === "repair"
            ? "Fix this cut?"
            : "Define this shot again?"
        }
        what={
          confirming?.kind === "repair"
            ? `A shot at the cut ${confirming.label}`
            : `The newest definition of ${confirming?.shotId ?? "this shot"}`
        }
        confirmLabel={confirming?.kind === "repair" ? "Fix the cut" : "Define again"}
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming?.kind === "define") {
            defineOne.mutate({
              sceneId: confirming.sceneId,
              shotId: confirming.shotId,
              confirmReplaceManual: true,
            });
          } else if (confirming?.kind === "repair") {
            repairCut.mutate({
              sceneId: confirming.sceneId,
              boundaryId: confirming.boundaryId,
              confirmReplaceManual: true,
            });
          }
          setConfirming(null);
        }}
      />
    </Paper>
  );
}
