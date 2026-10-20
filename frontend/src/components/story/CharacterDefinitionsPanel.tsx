import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { Link } from "react-router";

import {
  useCharacterDefinitions,
  useDefineAll,
  useDefineOne,
  type DefinitionEntry,
} from "../../api/characterDefinitions";
import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { CharacterDefinitionView } from "../characterLab/CharacterDefinitionView";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";

type CharacterDefinitionsPanelProps = {
  projectId: number;
};

const STATUS: Record<DefinitionEntry["status"], { label: string; color: string }> = {
  unlinked: { label: "Not linked", color: "gray" },
  not_defined: { label: "Not defined", color: "gray" },
  defined: { label: "Defined", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

function labPath(characterId: number): string {
  return `/lab/characters?character=${characterId}`;
}

type EntryRowProps = {
  entry: DefinitionEntry;
  /** True when nothing can be defined yet; the reason is shown once, above the list. */
  projectBlocked: boolean;
  busy: boolean;
  onDefine: () => void;
};

/**
 * One character: its status, the library character it is saved to and the version the project
 * pins, why its definition is out of date, the job's failure when the last run failed, and the
 * definition itself, read only.
 */
function EntryRow({ entry, projectBlocked, busy, onDefine }: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const job = entry.job;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
  const defined = entry.status === "defined" || entry.status === "out_of_date";
  // Why this one character cannot be defined, when that is about the character itself.
  const reason = projectBlocked || active ? null : entry.blocked_reason;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={120}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {entry.id}
        </Badge>
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {entry.name}
            </Text>
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
            {entry.character_id !== null && entry.character_name !== null && (
              <Anchor component={Link} to={labPath(entry.character_id)} size="sm">
                {entry.character_name}
              </Anchor>
            )}
            {entry.needs_confirmation && (
              <Badge
                variant="light"
                color="teal"
                title="Chosen from the Character Lab: defining it asks first, because it overwrites the profile"
              >
                from the library
              </Badge>
            )}
            {entry.pinned_version !== null && (
              <Badge variant="light" title="The version of the character this project uses">
                pins v{entry.pinned_version}
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
            <Alert color="red" p="xs" title="The last definition failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.definition !== null && (
            <Button size="compact-xs" variant="default" onClick={() => setOpen((value) => !value)}>
              {open ? "Hide the definition" : "Show the definition"}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy}
            onClick={onDefine}
          >
            {defined ? "Re-define" : "Define"}
          </Button>
        </Group>
      </Group>
      {entry.definition !== null && entry.version !== null && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title="Definition"
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <CharacterDefinitionView definition={entry.definition} />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

/**
 * The Character Definition stage: one model call per linked character writes its looks, default
 * clothes, voice and behaviour. The definition is saved onto the character's Character Lab
 * profile as a new version, and the project pins that version. **Define all** covers the
 * characters made for this project; one chosen from the library is defined on its own, after
 * the user confirms that its profile will be overwritten.
 */
export function CharacterDefinitionsPanel({ projectId }: CharacterDefinitionsPanelProps) {
  const { data, isLoading, isError, error } = useCharacterDefinitions(projectId);
  const defineAll = useDefineAll(projectId);
  const defineOne = useDefineOne(projectId);
  // The character waiting for the user to agree to overwrite its profile.
  const [confirming, setConfirming] = useState<DefinitionEntry | null>(null);

  const busy = defineAll.isPending || defineOne.isPending;
  const entries = data?.entries ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  // What "Define all" would start: the linked characters made for this project that may run.
  const allCount = entries.filter((entry) => entry.can_run && !entry.needs_confirmation).length;
  const skipped = defineAll.data?.skipped ?? [];

  const define = (entry: DefinitionEntry) => {
    if (entry.needs_confirmation) {
      setConfirming(entry);
    } else {
      defineOne.mutate({ discoveryId: entry.id, confirmOverwrite: false });
    }
  };

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Character definitions</Title>
            <Text size="sm" c="dimmed">
              Writes each character&apos;s looks, default clothes, voice and behaviour, and saves
              them to its Character Lab character as a new version that this project pins.
            </Text>
          </Stack>
          <Button
            onClick={() => defineAll.mutate()}
            loading={defineAll.isPending}
            disabled={isLoading || isError || busy || projectBlocked || allCount === 0}
          >
            Define all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the definitions">
            {describeError(error)}
          </Alert>
        )}
        {defineAll.isError && (
          <Alert color="red" title="Could not start the definitions">
            {describeError(defineAll.error)}
          </Alert>
        )}
        {defineOne.isError && (
          <Alert color="red" title="Could not start the definition">
            {describeError(defineOne.error)}
          </Alert>
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not started">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={item.discovery_id} size="sm">
                  {item.name}: {item.reason}
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
        {data && data.discovery_version === null && (
          <Text size="sm" c="dimmed">
            Find the characters first (above), link them to the Character Lab, then define them
            here.
          </Text>
        )}
        {entries.length > 0 && <Divider />}

        {entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            projectBlocked={projectBlocked}
            busy={busy}
            onDefine={() => define(entry)}
          />
        ))}
      </Stack>

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Overwrite this character?"
        centered
      >
        {confirming && (
          <Stack gap="md">
            <Text size="sm">
              {confirming.character_name ?? confirming.name} was chosen from the Character Lab.
              Defining it replaces its age, gender, species, appearance, outfit, personality,
              voice description and era with the new definition. What it has now stays readable in
              its version history.
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setConfirming(null)}>
                Cancel
              </Button>
              <Button
                color="red"
                onClick={() => {
                  defineOne.mutate({ discoveryId: confirming.id, confirmOverwrite: true });
                  setConfirming(null);
                }}
              >
                Define and overwrite
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}
