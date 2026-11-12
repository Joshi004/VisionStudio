import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useMakeThumbnails,
  useRunThumbnailIdeas,
  useSaveThumbnailIdeas,
  useThumbnails,
} from "../../api/thumbnails";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ThumbnailCard } from "./ThumbnailCard";
import { ThumbnailIdeasEditor } from "./ThumbnailIdeasEditor";

type ThumbnailsPanelProps = {
  projectId: number;
};

/**
 * The optional thumbnail step. The model writes four ideas (headline, where the headline goes,
 * who is on the picture); the owner edits them; each ticked idea becomes one picture; the app
 * draws the headline on it. One picture can be chosen. Nothing is deleted when the story
 * changes: old pictures stay and are marked out of date.
 */
export function ThumbnailsPanel({ projectId }: ThumbnailsPanelProps) {
  const { data, isLoading, isError, error } = useThumbnails(projectId);
  const run = useRunThumbnailIdeas(projectId);
  const save = useSaveThumbnailIdeas(projectId);
  const make = useMakeThumbnails(projectId);
  const [note, setNote] = useState("");

  const ideas = data?.ideas ?? null;
  const latest = ideas?.latest ?? null;
  const job = ideas?.job ?? null;
  const writing = isJobActive(job);
  const makingPictures =
    data?.thumbnails.some((thumbnail) => isJobActive(thumbnail.job)) ?? false;
  const blocked = ideas?.blocked_reason ?? null;

  const startRun = () => {
    const trimmed = note.trim();
    run.mutate(
      { feedback: trimmed === "" ? null : trimmed },
      { onSuccess: () => setNote("") },
    );
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Title order={4}>Thumbnail</Title>
            <Text size="sm" c="dimmed">
              An optional picture to represent the video. The model suggests
              four ideas, you edit them, and each idea you tick is made into one
              picture. The headline is drawn on top by the app, so the letters
              are always correct.
            </Text>
          </Stack>

          {blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the thumbnails">
              {describeError(error)}
            </Alert>
          )}
          {latest && (
            <Textarea
              label="A note for the model (optional)"
              description="For example: show the presenter more surprised, or no people at all."
              autosize
              minRows={1}
              maxRows={4}
              value={note}
              onChange={(event) => setNote(event.currentTarget.value)}
            />
          )}
          <Group>
            <Button
              onClick={startRun}
              loading={run.isPending || writing}
              disabled={
                isLoading || isError || blocked !== null || makingPictures
              }
            >
              {latest ? "Write ideas again" : "Write ideas"}
            </Button>
          </Group>
          {run.isError && (
            <Alert color="red" title="Could not start the thumbnail ideas">
              {describeError(run.error)}
            </Alert>
          )}
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          {job?.status === "failed" && (
            <Alert color="red" title="The last run failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {ideas?.out_of_date && latest && (
            <Alert color="yellow" title="The ideas are out of date">
              <Stack gap={4}>
                <Text size="sm">
                  Something these ideas were written from has changed. You can
                  still use them, or write new ones.
                </Text>
                {ideas.reasons.length > 0 && (
                  <List size="sm">
                    {ideas.reasons.map((reason) => (
                      <List.Item key={reason}>{reason}</List.Item>
                    ))}
                  </List>
                )}
              </Stack>
            </Alert>
          )}
        </Stack>
      </Paper>

      {latest && ideas && (
        <Stack gap="xs">
          <Group gap="xs">
            <Title order={5}>Ideas</Title>
            <Badge
              variant="light"
              color={latest.source === "manual" ? "blue" : "gray"}
            >
              Version {latest.version},{" "}
              {latest.source === "manual"
                ? "written by you"
                : "written by the model"}
            </Badge>
          </Group>
          {latest.feedback && (
            <Text size="sm" c="dimmed">
              Your note: {latest.feedback}
            </Text>
          )}
          <ThumbnailIdeasEditor
            key={latest.version}
            concepts={latest.content.concepts}
            cast={ideas.cast}
            places={ideas.places}
            busy={writing || makingPictures}
            saving={save.isPending}
            saveError={save.error}
            making={make.isPending}
            makeError={make.error}
            onSave={(concepts) => save.mutate(concepts)}
            onMake={(indexes) =>
              make.mutate({ conceptVersion: latest.version, indexes })
            }
          />
        </Stack>
      )}

      {data && data.thumbnails.length > 0 && (
        <Stack gap="xs">
          <Title order={5}>Pictures</Title>
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
            {data.thumbnails.map((thumbnail) => (
              <ThumbnailCard
                key={thumbnail.id}
                projectId={projectId}
                thumbnail={thumbnail}
              />
            ))}
          </SimpleGrid>
        </Stack>
      )}
    </Stack>
  );
}
