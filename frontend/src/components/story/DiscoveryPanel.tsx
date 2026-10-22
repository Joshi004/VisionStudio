import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useDiscovery,
  useDiscoveryVersion,
  useRunDiscovery,
  useSaveDiscovery,
  type DiscoveryKind,
} from "../../api/discovery";
import { useStoryBible } from "../../api/storyBible";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { DiscoveryListEditor } from "./DiscoveryListEditor";
import { ReplaceManualModal } from "./ReplaceManualModal";

type DiscoveryPanelProps = {
  projectId: number;
  kind: DiscoveryKind;
  /** Whether the project has a saved story. The lists are found in the saved text. */
  hasStory: boolean;
};

const TEXTS: Record<
  DiscoveryKind,
  { title: string; description: string; result: string; noun: string }
> = {
  characters: {
    title: "Characters",
    description: "The people and presences the story needs, with a short note on each.",
    result: "Characters found",
    noun: "character",
  },
  environments: {
    title: "Environments",
    description: "The places the story happens in, with a short note on each.",
    result: "Environments found",
    noun: "environment",
  },
};

/**
 * One discovery stage (the characters, or the environments): a Run / Re-run button, the state
 * of the job, the version picker and the list that was found. It follows the Story Bible
 * panel, and is used once for each kind.
 */
export function DiscoveryPanel({ projectId, kind, hasStory }: DiscoveryPanelProps) {
  const texts = TEXTS[kind];
  const { data, isLoading, isError, error } = useDiscovery(projectId, kind);
  const bible = useStoryBible(projectId);
  const run = useRunDiscovery(projectId, kind);
  const save = useSaveDiscovery(projectId, kind);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useDiscoveryVersion(projectId, kind, viewingOlder ? shownVersion : null);
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);

  // Why the button cannot be used yet. The server refuses the same cases.
  let blocker: string | null = null;
  if (!hasStory) {
    blocker = "Save the story above first: the list is found in the saved text.";
  } else if (bible.data && bible.data.latest === null) {
    blocker = "Run the Story Bible first: the list is found with its help.";
  } else if (bible.data?.out_of_date) {
    blocker = "The Story Bible is out of date. Re-run it first.";
  }

  const startRun = (confirmReplaceManual: boolean) => {
    // A new version is on its way: show it when it arrives.
    setPicked(null);
    run.mutate({ confirmReplaceManual });
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>{texts.title}</Title>
              <Text size="sm" c="dimmed">
                {texts.description}
              </Text>
            </Stack>
            <Group gap="sm" align="flex-end">
              {data && data.versions.length > 1 && (
                <Select
                  aria-label="Version"
                  w={190}
                  allowDeselect={false}
                  data={data.versions.map((version, index) => ({
                    value: String(version.version),
                    label: `Version ${version.version}${index === 0 ? " (newest)" : ""}`,
                  }))}
                  value={shownVersion === null ? null : String(shownVersion)}
                  onChange={(value) => value !== null && setPicked(Number(value))}
                />
              )}
              <Button
                variant="default"
                onClick={() => {
                  save.reset();
                  setPicked(null);
                  setEditing(true);
                }}
                disabled={!hasStory || editing || latest === null || active}
              >
                Edit
              </Button>
              <Button
                onClick={() => (data?.needs_confirmation ? setConfirming(true) : startRun(false))}
                loading={run.isPending || active}
                disabled={
                  blocker !== null ||
                  isLoading ||
                  isError ||
                  bible.isLoading ||
                  bible.isError ||
                  editing
                }
              >
                {latest ? "Re-run" : "Run"}
              </Button>
            </Group>
          </Group>

          {blocker !== null && (
            <Text size="sm" c="dimmed">
              {blocker}
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title={`Could not load the ${kind}`}>
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title={`Could not start the ${kind} search`}>
              {describeError(run.error)}
            </Alert>
          )}
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          {job?.status === "failed" && (
            <Alert color="red" title="The last run failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {data?.out_of_date && !viewingOlder && (
            <Alert color="yellow" title="Out of date">
              The story or the Story Bible has changed since this list was made. Press Re-run to
              make a new one.
            </Alert>
          )}
        </Stack>
      </Paper>

      {editing && latest && (
        <Paper withBorder p="md" radius="md">
          <DiscoveryListEditor
            noun={texts.noun}
            initial={latest.items}
            saving={save.isPending}
            error={save.error}
            onSave={(items) => save.mutate(items, { onSuccess: () => setEditing(false) })}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {shown && !editing && (
        <ArtifactViewer
          title={texts.result}
          version={shown.version}
          source={shown.source}
          jobId={shown.job_id}
          createdAt={shown.created_at}
        >
          <Stack gap="xs">
            {shown.items.map((item) => (
              <Group key={item.id} align="flex-start" wrap="nowrap" gap="sm">
                <Badge
                  variant="outline"
                  color="gray"
                  miw={120}
                  style={{ flexShrink: 0, textTransform: "none" }}
                >
                  {item.id}
                </Badge>
                <Stack gap={0}>
                  <Text size="sm" fw={500}>
                    {item.name}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {item.description}
                  </Text>
                </Stack>
              </Group>
            ))}
          </Stack>
        </ArtifactViewer>
      )}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}
      <ReplaceManualModal
        opened={confirming}
        title={`Find the ${texts.noun}s again?`}
        what={`The newest list of ${texts.noun}s`}
        confirmLabel="Re-run"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          startRun(true);
        }}
      />
    </Stack>
  );
}
