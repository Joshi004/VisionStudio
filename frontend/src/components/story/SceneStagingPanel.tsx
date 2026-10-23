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
  useSaveSceneStaging,
  useSceneStaging,
  useStageAllScenes,
  useStageOneScene,
  type SceneStagingEntry,
  type StagingEnvironment,
  type StagingSaveInput,
} from "../../api/sceneStaging";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { PromptHoverCard } from "./PromptHoverCard";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { SceneStagingEditor } from "./SceneStagingEditor";
import { SceneStagingView } from "./SceneStagingView";

type SceneStagingPanelProps = {
  projectId: number;
};

const STATUS: Record<SceneStagingEntry["status"], { label: string; color: string }> = {
  not_staged: { label: "Not staged", color: "gray" },
  staged: { label: "Staged", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

type EntryRowProps = {
  entry: SceneStagingEntry;
  characterNames: Record<string, string>;
  characters: { id: string; name: string }[];
  environments: StagingEnvironment[];
  /** True when nothing can be staged yet; the reason is shown once, above the list. */
  projectBlocked: boolean;
  busy: boolean;
  onStage: () => void;
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (staging: StagingSaveInput, done: () => void) => void;
};

/** One scene: its status, why its staging is out of date, and the staging itself, which can be edited. */
function EntryRow({
  entry,
  characterNames,
  characters,
  environments,
  projectBlocked,
  busy,
  onStage,
  saving,
  saveError,
  onStartEdit,
  onSave,
}: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const job = entry.job;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
  const staged = entry.status === "staged" || entry.status === "out_of_date";
  const reason = projectBlocked || active ? null : entry.blocked_reason;
  // The editor offers the zones of the environment the staging was written for.
  const zoneIds = new Set(entry.staging?.placements.map((item) => item.zone));
  const environment =
    environments.find((item) => item.zones.some((zone) => zoneIds.has(zone.id))) ??
    environments[0] ??
    null;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge variant="outline" color="gray" miw={40} style={{ flexShrink: 0, textTransform: "none" }}>
          {entry.index}
        </Badge>
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {entry.title}
            </Text>
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
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          </Group>
          <Text size="sm" c="dimmed">
            {entry.description}
          </Text>
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
            <Alert color="red" p="xs" title="The last staging failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.staging !== null && (
            <Button size="compact-xs" variant="default" onClick={() => setOpen((value) => !value)}>
              {open ? "Hide the staging" : "Show the staging"}
            </Button>
          )}
          {entry.staging !== null && (
            <Button
              size="compact-sm"
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
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy || editing}
            onClick={onStage}
          >
            {staged ? "Re-stage" : "Stage"}
          </Button>
        </Group>
      </Group>
      {editing && entry.staging !== null && (
        <Paper withBorder p="md" radius="sm" ml={34}>
          <SceneStagingEditor
            initial={entry.staging}
            characters={characters}
            environment={environment}
            saving={saving}
            error={saveError}
            onSave={(staging) => onSave(staging, () => setEditing(false))}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {entry.staging !== null && entry.version !== null && !editing && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title="Staging"
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <SceneStagingView staging={entry.staging} characterNames={characterNames} />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

/**
 * The Scene Staging stage: one model call per scene decides where each character stands, which
 * way they face, which side of the screen they are on and what is behind them, so two people in
 * one room keep their own backgrounds. A scene can be staged once it is defined and its events
 * are extracted. **Stage all** covers every scene whose staging is missing or out of date.
 */
export function SceneStagingPanel({ projectId }: SceneStagingPanelProps) {
  const { data, isLoading, isError, error } = useSceneStaging(projectId);
  const stageAll = useStageAllScenes(projectId);
  const stageOne = useStageOneScene(projectId);
  const save = useSaveSceneStaging(projectId);
  // The scene whose newest staging the user wrote, waiting for "yes, stage it again".
  const [confirming, setConfirming] = useState<SceneStagingEntry | null>(null);

  const busy = stageAll.isPending || stageOne.isPending;
  const entries = data?.entries ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  const characterNames = Object.fromEntries(
    (data?.characters ?? []).map((character) => [character.id, character.name]),
  );
  const allCount = entries.filter((entry) => entry.can_run && entry.status !== "staged").length;
  const skipped = stageAll.data?.skipped ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Scene staging</Title>
            <Text size="sm" c="dimmed">
              Decides where each character stands in the place, which way they face, which side of
              the screen they are on and what is behind them. Every shot of the scene follows it.
            </Text>
          </Stack>
          <Button
            onClick={() => stageAll.mutate()}
            loading={stageAll.isPending}
            disabled={isLoading || isError || busy || projectBlocked || allCount === 0}
          >
            Stage all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the scene staging">
            {describeError(error)}
          </Alert>
        )}
        {stageAll.isError && (
          <Alert color="red" title="Could not start the scene staging">
            {describeError(stageAll.error)}
          </Alert>
        )}
        {stageOne.isError && (
          <Alert color="red" title="Could not start the scene staging">
            {describeError(stageOne.error)}
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

        {entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            characterNames={characterNames}
            characters={data?.characters ?? []}
            environments={data?.environments ?? []}
            projectBlocked={projectBlocked}
            busy={busy}
            onStage={() =>
              entry.needs_confirmation
                ? setConfirming(entry)
                : stageOne.mutate({ sceneId: entry.id, confirmReplaceManual: false })
            }
            saving={save.isPending}
            saveError={save.error}
            onStartEdit={() => save.reset()}
            onSave={(staging, done) =>
              save.mutate({ sceneId: entry.id, staging }, { onSuccess: done })
            }
          />
        ))}
      </Stack>
      <ReplaceManualModal
        opened={confirming !== null}
        title="Stage the scene again?"
        what={`The newest staging of ${confirming?.title ?? "this scene"}`}
        confirmLabel="Re-stage"
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming !== null) {
            stageOne.mutate({ sceneId: confirming.id, confirmReplaceManual: true });
          }
          setConfirming(null);
        }}
      />
    </Paper>
  );
}
