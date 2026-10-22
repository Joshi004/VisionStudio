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
import {
  useSaveShotReferences,
  useSelectAllReferences,
  useSelectOneShotReferences,
  useSelectSceneReferences,
  useShotReferences,
  type ReferencePicture,
  type SceneShotReferences,
  type ShotReferenceEntry,
} from "../../api/shotReferences";
import { PromptHoverCard } from "./PromptHoverCard";
import { pictureLabel } from "./referencePictureFormat";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { ShotReferencesEditor } from "./ShotReferencesEditor";

type ShotReferencesPanelProps = {
  projectId: number;
};

const STATUS: Record<
  ShotReferenceEntry["status"],
  { label: string; color: string }
> = {
  not_selected: { label: "Not chosen", color: "gray" },
  selected: { label: "Chosen", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

const FRAMING_LABELS: Record<string, string> = {
  close_up: "close-up",
  medium: "medium",
  wide: "wide",
};

/** One picture of the manifest. A character is shown at 2:3 and a place at 16:9. */
function Thumbnail({ picture }: { picture: ReferencePicture }) {
  const environment = picture.kind === "environment";
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
        {picture.order}. {pictureLabel(picture)}
      </Text>
      {picture.fallback && (
        <Text size="xs" c="dimmed">
          default look (fallback)
        </Text>
      )}
      {picture.reason != null && (
        <Text size="xs" c="dimmed" style={{ wordBreak: "break-word" }}>
          {picture.reason}
        </Text>
      )}
    </Stack>
  );
}

/** How the manifest was chosen, in a few words. */
function methodLabel(manifest: NonNullable<ShotReferenceEntry["manifest"]>) {
  if (manifest.method === "llm") {
    return "Chosen by the model";
  }
  if (manifest.method === "manual") {
    return "Chosen by you";
  }
  return manifest.fallback_reason != null
    ? "Chosen by rule (model not used)"
    : "Chosen by rule";
}

/** A reason that only says a shot is already done or being done: not worth an alert. */
function isRoutineSkip(reason: string): boolean {
  return reason.startsWith("Already") || reason.includes("being chosen");
}

type ShotRowProps = {
  entry: ShotReferenceEntry;
  busy: boolean;
  onSelect: () => void;
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (labImageIds: number[], done: () => void) => void;
};

/**
 * One shot: its status, why it is out of date, and the pictures it is generated from, which can
 * be chosen by hand.
 */
function ShotRow({
  entry,
  busy,
  onSelect,
  saving,
  saveError,
  onStartEdit,
  onSave,
}: ShotRowProps) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const { shot, manifest, version } = entry;
  const status = STATUS[entry.status];
  const chosen = entry.status !== "not_selected";
  const choosing = isJobActive(entry.job);
  // The newest model job failed and nothing newer was stored: say why.
  const failed =
    entry.job?.status === "failed" && entry.status !== "selected"
      ? entry.job.error
      : null;

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
            {choosing && (
              <Badge
                variant="light"
                color="blue"
                leftSection={<Loader size={10} />}
                title={entry.job?.phase ?? undefined}
              >
                Choosing...
              </Badge>
            )}
            {version !== null && (
              <PromptHoverCard
                jobId={version.job_id}
                source={version.source}
                codeNote="Chosen by the fixed rule in code. No model was asked."
              >
                <Badge variant="light" style={{ cursor: "help" }}>
                  v{version.version}
                </Badge>
              </PromptHoverCard>
            )}
            {manifest !== null && (
              <Badge
                variant="light"
                color={manifest.method === "llm" ? "teal" : "gray"}
              >
                {methodLabel(manifest)}
              </Badge>
            )}
            {manifest !== null && (
              <Badge variant="light" color="gray">
                {FRAMING_LABELS[manifest.framing] ?? manifest.framing} framing,{" "}
                {manifest.references.length}{" "}
                {manifest.references.length === 1 ? "picture" : "pictures"}
              </Badge>
            )}
            <Text size="sm" style={{ wordBreak: "break-word" }}>
              {shot.description}
            </Text>
          </Group>
          {!entry.can_run && entry.blocked_reason !== null && (
            <Text size="xs" c="dimmed">
              {entry.blocked_reason}
            </Text>
          )}
          {failed !== null && (
            <Text size="xs" c="red">
              {failed}
            </Text>
          )}
          {manifest?.fallback_reason != null && (
            <Text size="xs" c="dimmed">
              The model was not used: {manifest.fallback_reason}
            </Text>
          )}
          {entry.reasons.map((text) => (
            <Text key={text} size="xs" c="yellow.8">
              {text}
            </Text>
          ))}
          {manifest?.notes.map((text) => (
            <Text key={text} size="xs" c="dimmed">
              {text}
            </Text>
          ))}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {manifest !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the references" : "Show the references"}
            </Button>
          )}
          {manifest !== null && (
            <Button
              size="compact-xs"
              variant="default"
              disabled={!entry.can_run || busy || choosing || editing}
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
            disabled={
              !entry.can_run || busy || editing || entry.status === "selected"
            }
            onClick={onSelect}
          >
            {chosen ? "Select again" : "Select references"}
          </Button>
        </Group>
      </Group>
      {editing && manifest !== null && (
        <Paper withBorder p="md" radius="sm">
          <ShotReferencesEditor
            manifest={manifest}
            saving={saving}
            error={saveError}
            onSave={(ids) => onSave(ids, () => setEditing(false))}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {manifest !== null && !editing && (
        <Collapse expanded={open}>
          <Group gap="md" align="flex-start" pt={4}>
            {manifest.references.map((picture) => (
              <Thumbnail key={picture.order} picture={picture} />
            ))}
          </Group>
        </Collapse>
      )}
    </Stack>
  );
}

type SceneRowProps = {
  scene: SceneShotReferences;
  busy: boolean;
  onSelectScene: () => void;
  onSelectShot: (shot: ShotReferenceEntry) => void;
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (shotId: string, labImageIds: number[], done: () => void) => void;
};

/** One scene: how many of its shots have their references, and its shots. */
function SceneRow({
  scene,
  busy,
  onSelectScene,
  onSelectShot,
  saving,
  saveError,
  onStartEdit,
  onSave,
}: SceneRowProps) {
  const chosen = scene.shots.filter((shot) => shot.status === "selected").length;
  const outOfDate = scene.shots.filter(
    (shot) => shot.status === "out_of_date",
  ).length;
  // What "Select references" would do for this scene.
  const todo = scene.shots.filter(
    (shot) => shot.can_run && shot.status !== "selected",
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
            {chosen} of {scene.shots.length} chosen
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
          onClick={onSelectScene}
          style={{ flexShrink: 0 }}
        >
          Select references
        </Button>
      </Group>
      {scene.shots.length > 0 && (
        <Stack gap="sm" ml={48}>
          {scene.shots.map((entry) => (
            <ShotRow
              key={entry.shot.id}
              entry={entry}
              busy={busy}
              onSelect={() => onSelectShot(entry)}
              saving={saving}
              saveError={saveError}
              onStartEdit={onStartEdit}
              onSave={(ids, done) => onSave(entry.shot.id, ids, done)}
            />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

/**
 * The Reference selection stage: for each defined shot, the smallest set of pictures it is
 * generated from. The language model chooses them from a catalog and says why, and code checks
 * the choice; the fixed rule (the framing of the shot gives the angles of each visible
 * character, taken from the look the scene uses, then the environment's picture, at most nine
 * in all) is the fallback and can be the only method (a setting). A shot's pictures are chosen
 * by themselves when it is defined.
 */
export function ShotReferencesPanel({ projectId }: ShotReferencesPanelProps) {
  const { data, isLoading, isError, error } = useShotReferences(projectId);
  const selectAll = useSelectAllReferences(projectId);
  const selectScene = useSelectSceneReferences(projectId);
  const selectOne = useSelectOneShotReferences(projectId);
  const save = useSaveShotReferences(projectId);
  // The shot whose pictures the user chose, waiting for "yes, choose them again".
  const [confirming, setConfirming] = useState<{
    sceneId: string;
    shotId: string;
  } | null>(null);

  const entries = data?.entries ?? [];
  const busy =
    selectAll.isPending || selectScene.isPending || selectOne.isPending;
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  // What "Select all" would do: the shots that may be chosen and have no current manifest.
  const allCount = entries.reduce(
    (sum, scene) =>
      sum +
      scene.shots.filter((shot) => shot.can_run && shot.status !== "selected")
        .length,
    0,
  );
  // The shots the last press could not do, with why (for example a missing picture).
  const skipped = [
    ...(selectAll.data?.skipped ?? []),
    ...(selectScene.data?.skipped ?? []),
    ...(selectOne.data?.skipped ?? []),
  ].filter((item) => item.shot_id !== null);
  // The shots the last press handed to the language model: their pictures appear as each ends.
  const queuedCount =
    (selectAll.data?.queued.length ?? 0) +
    (selectScene.data?.queued.length ?? 0) +
    (selectOne.data?.queued.length ?? 0);
  const choosingCount = entries.reduce(
    (sum, scene) => sum + scene.shots.filter((shot) => isJobActive(shot.job)).length,
    0,
  );

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Shot references</Title>
            <Text size="sm" c="dimmed">
              Chooses the pictures each shot is generated from: the visible
              characters, shown from the angles that suit the shot, in the look
              the scene uses, and the place. The fewest that are enough, never
              more than nine, and never the narration. The language model
              chooses and says why; when its answer cannot be used, the fixed
              rule for the shot&apos;s framing chooses instead (the setting
              &quot;How shot references are chosen&quot; can turn the model
              off). Done by itself when a shot is defined.
            </Text>
          </Stack>
          <Button
            onClick={() => selectAll.mutate()}
            loading={selectAll.isPending}
            disabled={
              isLoading || isError || busy || projectBlocked || allCount === 0
            }
            style={{ flexShrink: 0 }}
          >
            Select all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the shot references">
            {describeError(error)}
          </Alert>
        )}
        {[selectAll, selectScene, selectOne].map(
          (mutation, position) =>
            mutation.isError && (
              <Alert
                key={position}
                color="red"
                title="Could not choose the references"
              >
                {describeError(mutation.error)}
              </Alert>
            ),
        )}
        {(queuedCount > 0 || choosingCount > 0) && (
          <Alert color="blue" title="Choosing with the language model">
            {choosingCount > 0
              ? `${choosingCount} ${choosingCount === 1 ? "shot is" : "shots are"} being chosen. `
              : ""}
            Each shot&apos;s pictures appear when its model call ends.
          </Alert>
        )}
        {skipped.some((item) => !isRoutineSkip(item.reason)) && (
          <Alert color="blue" title="Not chosen">
            <Stack gap={2}>
              {skipped
                .filter((item) => !isRoutineSkip(item.reason))
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
            onSelectScene={() => selectScene.mutate(scene.id)}
            onSelectShot={(shot) =>
              shot.needs_confirmation
                ? setConfirming({ sceneId: scene.id, shotId: shot.shot.id })
                : selectOne.mutate({
                    sceneId: scene.id,
                    shotId: shot.shot.id,
                    confirmReplaceManual: false,
                  })
            }
            saving={save.isPending}
            saveError={save.error}
            onStartEdit={() => save.reset()}
            onSave={(shotId, labImageIds, done) =>
              save.mutate(
                { sceneId: scene.id, shotId, labImageIds },
                { onSuccess: done },
              )
            }
          />
        ))}
      </Stack>
      <ReplaceManualModal
        opened={confirming !== null}
        title="Choose the pictures again?"
        what={`The newest choice of pictures for ${confirming?.shotId ?? "this shot"}`}
        confirmLabel="Choose again"
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming !== null) {
            selectOne.mutate({ ...confirming, confirmReplaceManual: true });
          }
          setConfirming(null);
        }}
      />
    </Paper>
  );
}
