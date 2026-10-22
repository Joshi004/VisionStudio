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
  useExtractAllEvents,
  useExtractOneSceneEvents,
  useSaveSceneEvents,
  useSceneEvents,
  type SceneEventInput,
  type SceneEventsEntry,
} from "../../api/sceneEvents";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import type { SpeechMode } from "../projects/speechModes";
import { ArtifactViewer } from "./ArtifactViewer";
import { PromptHoverCard } from "./PromptHoverCard";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { SceneEventsEditor } from "./SceneEventsEditor";
import { SceneEventsView } from "./SceneEventsView";

type SceneEventsPanelProps = {
  projectId: number;
  /** The project's speech mode, which decides the event types an edit may use. */
  speechMode: SpeechMode;
};

const STATUS: Record<
  SceneEventsEntry["status"],
  { label: string; color: string }
> = {
  not_extracted: { label: "Not extracted", color: "gray" },
  extracted: { label: "Extracted", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

type EntryRowProps = {
  speechMode: SpeechMode;
  entry: SceneEventsEntry;
  characterNames: Record<string, string>;
  characters: { id: string; name: string }[];
  /** True when nothing can be extracted yet; the reason is shown once, above the list. */
  projectBlocked: boolean;
  busy: boolean;
  onExtract: () => void;
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (events: SceneEventInput[], done: () => void) => void;
};

/**
 * One scene: its status, why its events are out of date, the job's failure when the last run
 * failed, and the events themselves, which can be edited by hand.
 */
function EntryRow({
  speechMode,
  entry,
  characterNames,
  characters,
  projectBlocked,
  busy,
  onExtract,
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
  const extracted =
    entry.status === "extracted" || entry.status === "out_of_date";
  // Why this one scene cannot be extracted, when that is about the scene itself.
  const reason = projectBlocked || active ? null : entry.blocked_reason;
  const uncovered = entry.events?.uncovered.length ?? 0;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={40}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
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
            {entry.events !== null && (
              <Badge variant="light" color="gray">
                {entry.events.events.length} events
              </Badge>
            )}
            {uncovered > 0 && (
              <Badge
                variant="light"
                color="yellow"
                title="Pieces of the scene's text that no narration or dialogue event covers"
              >
                {uncovered} not covered
              </Badge>
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
            <Alert color="red" p="xs" title="The last extraction failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.events !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the events" : "Show the events"}
            </Button>
          )}
          {entry.events !== null && (
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
            onClick={onExtract}
          >
            {extracted ? "Re-extract" : "Extract"}
          </Button>
        </Group>
      </Group>
      {editing && entry.events !== null && (
        <Paper withBorder p="md" radius="sm" ml={34}>
          <SceneEventsEditor
            speechMode={speechMode}
            initial={entry.events.events}
            characters={characters}
            saving={saving}
            error={saveError}
            onSave={(events) => onSave(events, () => setEditing(false))}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {entry.events !== null && entry.version !== null && !editing && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title="Events"
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <SceneEventsView
              events={entry.events}
              characterNames={characterNames}
            />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

/**
 * The Event Extraction stage: one model call per scene lists what happens in it, in story order,
 * as narration, dialogue, actions, sounds and pauses. A scene can only be extracted once it is
 * defined. **Extract all** covers every defined scene whose events are missing or out of date.
 */
export function SceneEventsPanel({ projectId, speechMode }: SceneEventsPanelProps) {
  const { data, isLoading, isError, error } = useSceneEvents(projectId);
  const extractAll = useExtractAllEvents(projectId);
  const extractOne = useExtractOneSceneEvents(projectId);
  const save = useSaveSceneEvents(projectId);
  // The scene whose newest events the user wrote, waiting for "yes, extract them again".
  const [confirming, setConfirming] = useState<SceneEventsEntry | null>(null);

  const busy = extractAll.isPending || extractOne.isPending;
  const entries = data?.entries ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  const characterNames = Object.fromEntries(
    (data?.characters ?? []).map((character) => [character.id, character.name]),
  );
  // What "Extract all" would start: the scenes that may run and are not extracted and current.
  const allCount = entries.filter(
    (entry) => entry.can_run && entry.status !== "extracted",
  ).length;
  const skipped = extractAll.data?.skipped ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Scene events</Title>
            <Text size="sm" c="dimmed">
              Lists what happens in each scene, in order: narration, dialogue,
              actions, sounds and pauses. The spoken words are checked against
              the scene&apos;s text.
            </Text>
          </Stack>
          <Button
            onClick={() => extractAll.mutate()}
            loading={extractAll.isPending}
            disabled={
              isLoading || isError || busy || projectBlocked || allCount === 0
            }
          >
            Extract all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the scene events">
            {describeError(error)}
          </Alert>
        )}
        {extractAll.isError && (
          <Alert color="red" title="Could not start the event extraction">
            {describeError(extractAll.error)}
          </Alert>
        )}
        {extractOne.isError && (
          <Alert color="red" title="Could not start the event extraction">
            {describeError(extractOne.error)}
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
            speechMode={speechMode}
            entry={entry}
            characterNames={characterNames}
            projectBlocked={projectBlocked}
            busy={busy}
            characters={data?.characters ?? []}
            onExtract={() =>
              entry.needs_confirmation
                ? setConfirming(entry)
                : extractOne.mutate({ sceneId: entry.id, confirmReplaceManual: false })
            }
            saving={save.isPending}
            saveError={save.error}
            onStartEdit={() => save.reset()}
            onSave={(events, done) =>
              save.mutate({ sceneId: entry.id, events }, { onSuccess: done })
            }
          />
        ))}
      </Stack>
      <ReplaceManualModal
        opened={confirming !== null}
        title="Extract the events again?"
        what={`The newest events of ${confirming?.title ?? "this scene"}`}
        confirmLabel="Re-extract"
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming !== null) {
            extractOne.mutate({ sceneId: confirming.id, confirmReplaceManual: true });
          }
          setConfirming(null);
        }}
      />
    </Paper>
  );
}
