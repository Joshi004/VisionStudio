import { useState } from "react";
import { Alert, Button, Group, Loader, Paper, Select, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useRunStoryBible,
  useSaveStoryBible,
  useStoryBible,
  useStoryBibleVersion,
} from "../../api/storyBible";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { StoryBibleEditor } from "./StoryBibleEditor";

type StoryBiblePanelProps = {
  projectId: number;
  /** Whether the project has a saved story. The Story Bible is written from the saved text. */
  hasStory: boolean;
};

/**
 * The Story Bible stage: a Run / Re-run button, the state of the job, the version picker and
 * the bible itself. This is the pattern every later story stage follows.
 */
export function StoryBiblePanel({ projectId, hasStory }: StoryBiblePanelProps) {
  const { data, isLoading, isError, error } = useStoryBible(projectId);
  const run = useRunStoryBible(projectId);
  const save = useSaveStoryBible(projectId);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useStoryBibleVersion(projectId, viewingOlder ? shownVersion : null);
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);

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
              <Title order={4}>Story Bible</Title>
              <Text size="sm" c="dimmed">
                The story's world, tone and rules, written once and shared by every later stage.
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
                disabled={!hasStory || isLoading || isError || editing}
              >
                {latest ? "Re-run" : "Run"}
              </Button>
            </Group>
          </Group>

          {!hasStory && (
            <Text size="sm" c="dimmed">
              Save the story above first: the Story Bible is written from the saved text.
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the Story Bible">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the Story Bible">
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
              The story has changed since this version was written. Press Re-run to write a new
              one.
            </Alert>
          )}
        </Stack>
      </Paper>

      {editing && latest && (
        <Paper withBorder p="md" radius="md">
          <StoryBibleEditor
            initial={latest.content}
            saving={save.isPending}
            error={save.error}
            onSave={(content) => save.mutate(content, { onSuccess: () => setEditing(false) })}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {shown && !editing && (
        <ArtifactViewer
          title="Result"
          version={shown.version}
          source={shown.source}
          jobId={shown.job_id}
          createdAt={shown.created_at}
          data={shown.content}
        />
      )}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}
      <ReplaceManualModal
        opened={confirming}
        title="Run the Story Bible again?"
        what="The newest Story Bible"
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
