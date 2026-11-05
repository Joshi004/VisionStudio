import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Image,
  List,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useChooseThumbnail,
  useMakeThumbnails,
  useRunThumbnailIdeas,
  useSaveThumbnailIdeas,
  useSetThumbnailHeadline,
  useThumbnails,
  type Thumbnail,
} from "../../api/thumbnails";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
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

type ThumbnailCardProps = {
  projectId: number;
  thumbnail: Thumbnail;
};

/** One picture with its headline, a way to change the headline, choose it and download it. */
function ThumbnailCard({ projectId, thumbnail }: ThumbnailCardProps) {
  const setHeadline = useSetThumbnailHeadline(projectId);
  const choose = useChooseThumbnail(projectId);
  const [headline, setHeadlineText] = useState(thumbnail.headline);
  const active = isJobActive(thumbnail.job);
  const headlineChanged = headline.trim() !== thumbnail.headline;
  const ratio =
    thumbnail.width && thumbnail.height
      ? thumbnail.width / thumbnail.height
      : 16 / 9;

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={500}>
            Idea {thumbnail.concept_index + 1}, version{" "}
            {thumbnail.concept_version}
          </Text>
          <Group gap={4}>
            {thumbnail.chosen && <Badge color="green">Chosen</Badge>}
            {thumbnail.reasons.length > 0 && (
              <Badge color="yellow">Out of date</Badge>
            )}
          </Group>
        </Group>

        {thumbnail.has_picture && thumbnail.url ? (
          <Image
            src={thumbnail.url}
            alt={thumbnail.headline}
            radius="sm"
            style={{ aspectRatio: ratio }}
          />
        ) : (
          <Stack align="center" justify="center" gap="xs" py="xl">
            {active && <Loader size="sm" />}
            {thumbnail.job && thumbnail.job.status !== "succeeded" && (
              <JobStatusBadge job={thumbnail.job} />
            )}
            {!active && thumbnail.error && (
              <Alert color="red" title="No picture was made">
                {thumbnail.error}
              </Alert>
            )}
          </Stack>
        )}

        {thumbnail.reasons.length > 0 && (
          <List size="xs" c="dimmed">
            {thumbnail.reasons.map((reason) => (
              <List.Item key={reason}>{reason}</List.Item>
            ))}
          </List>
        )}

        {thumbnail.has_picture && (
          <>
            <Group align="flex-end" wrap="nowrap">
              <TextInput
                label="Headline"
                style={{ flex: 1 }}
                maxLength={40}
                value={headline}
                onChange={(event) => setHeadlineText(event.currentTarget.value)}
              />
              <Button
                variant="default"
                onClick={() =>
                  setHeadline.mutate({
                    thumbnailId: thumbnail.id,
                    headline: headline.trim(),
                  })
                }
                loading={setHeadline.isPending}
                disabled={!headlineChanged || headline.trim() === ""}
              >
                Redraw
              </Button>
            </Group>
            {setHeadline.isError && (
              <Alert color="red" title="Could not change the headline">
                {describeError(setHeadline.error)}
              </Alert>
            )}
            {choose.isError && (
              <Alert color="red" title="Could not choose the thumbnail">
                {describeError(choose.error)}
              </Alert>
            )}
            <Group gap="xs">
              <Button
                variant={thumbnail.chosen ? "light" : "filled"}
                onClick={() =>
                  choose.mutate({
                    thumbnailId: thumbnail.id,
                    chosen: !thumbnail.chosen,
                  })
                }
                loading={choose.isPending}
              >
                {thumbnail.chosen ? "Not chosen" : "Choose"}
              </Button>
              {thumbnail.url && (
                <Button
                  component="a"
                  href={thumbnail.url}
                  download={`thumbnail-${thumbnail.id}.png`}
                  variant="default"
                >
                  Download
                </Button>
              )}
              {thumbnail.width && thumbnail.height && (
                <Text size="xs" c="dimmed">
                  {thumbnail.width} x {thumbnail.height}
                </Text>
              )}
            </Group>
          </>
        )}
      </Stack>
    </Paper>
  );
}
