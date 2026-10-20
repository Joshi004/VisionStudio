import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Collapse,
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
import { useRunScenes, useSceneVersion, useScenes, type SceneItem } from "../../api/scenes";
import { useStoryBible } from "../../api/storyBible";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";

type ScenesPanelProps = {
  projectId: number;
  /** Whether the project has a saved story. The scenes are found in the saved text. */
  hasStory: boolean;
};

/** One scene: its title, id and description, and the exact slice of the story it owns. */
function SceneRow({ scene }: { scene: SceneItem }) {
  const [open, setOpen] = useState(false);
  return (
    <Stack gap={4}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge variant="light" color="gray" style={{ flexShrink: 0 }}>
          {scene.index}
        </Badge>
        <Stack gap={0} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {scene.title}
            </Text>
            <Badge variant="outline" color="gray" style={{ textTransform: "none" }}>
              {scene.id}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {scene.description}
          </Text>
        </Stack>
        <Button
          size="compact-xs"
          variant="default"
          style={{ flexShrink: 0 }}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Hide the text" : "Show the text"}
        </Button>
      </Group>
      <Collapse expanded={open}>
        <Paper withBorder p="sm" radius="sm" ml={34}>
          <Stack gap={6}>
            <Text size="xs" c="dimmed">
              Opens with: {scene.starts_with}
            </Text>
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {scene.text.trim()}
            </Text>
          </Stack>
        </Paper>
      </Collapse>
    </Stack>
  );
}

/**
 * The scene discovery stage: a Run / Re-run button, the state of the job, the version picker
 * and the list of scenes that was found. It follows the discovery panels (characters and
 * environments) and runs beside them. Each scene shows the exact slice of the story it owns;
 * the slices of all the scenes, joined in order, are the whole story.
 */
export function ScenesPanel({ projectId, hasStory }: ScenesPanelProps) {
  const { data, isLoading, isError, error } = useScenes(projectId);
  const bible = useStoryBible(projectId);
  const run = useRunScenes(projectId);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useSceneVersion(projectId, viewingOlder ? shownVersion : null);
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);

  // Why the button cannot be used yet. The server refuses the same cases.
  let blocker: string | null = null;
  if (!hasStory) {
    blocker = "Save the story above first: the scenes are found in the saved text.";
  } else if (bible.data && bible.data.latest === null) {
    blocker = "Run the Story Bible first: the scenes are found with its help.";
  } else if (bible.data?.out_of_date) {
    blocker = "The Story Bible is out of date. Re-run it first.";
  }

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Scenes</Title>
              <Text size="sm" c="dimmed">
                The story divided into its scenes. Each scene owns one slice of the original text,
                and together the slices are the whole story.
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
                onClick={() => {
                  // A new version is on its way: show it when it arrives.
                  setPicked(null);
                  run.mutate();
                }}
                loading={run.isPending || active}
                disabled={
                  blocker !== null || isLoading || isError || bible.isLoading || bible.isError
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
            <Alert color="red" title="Could not load the scenes">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the scene search">
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
              The story or the Story Bible has changed since these scenes were made. Press Re-run
              to make new ones.
            </Alert>
          )}
        </Stack>
      </Paper>

      {shown && (
        <ArtifactViewer
          title="Scenes found"
          version={shown.version}
          source={shown.source}
          jobId={shown.job_id}
          createdAt={shown.created_at}
        >
          <Stack gap="sm">
            {shown.scenes.map((scene) => (
              <SceneRow key={scene.id} scene={scene} />
            ))}
          </Stack>
        </ArtifactViewer>
      )}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}
    </Stack>
  );
}
