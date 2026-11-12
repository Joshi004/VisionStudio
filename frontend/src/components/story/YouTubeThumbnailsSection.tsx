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
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useMakeThumbnails,
  useRunThumbnailIdeas,
  useSaveThumbnailIdeas,
  useThumbnails,
  type Thumbnail,
} from "../../api/thumbnails";
import type { YouTubeThumbnail } from "../../api/youtube";
import { stepPath } from "../board/boardSteps";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ThumbnailCard } from "./ThumbnailCard";
import { ThumbnailIdeasEditor } from "./ThumbnailIdeasEditor";

const STATUS: Record<
  YouTubeThumbnail["status"],
  { label: string; color: string }
> = {
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
  making: { label: "Being made", color: "blue" },
  none: { label: "None yet", color: "gray" },
};

type YouTubeThumbnailsSectionProps = {
  projectId: number;
  /** The chosen thumbnail and whether it is current for the render being published. */
  thumbnail: YouTubeThumbnail;
};

/**
 * The thumbnails of the project, inside the Publish panel: the newest picture of each of the four
 * ideas, with Choose, the headline, Make again, the ideas to edit and new ideas to ask for. Older
 * pictures are behind one control. Upload waits until every picture of the newest ideas is
 * finished (the panel's reasons under Upload say so).
 */
export function YouTubeThumbnailsSection({
  projectId,
  thumbnail,
}: YouTubeThumbnailsSectionProps) {
  const { data, isLoading, isError, error } = useThumbnails(projectId);
  const run = useRunThumbnailIdeas(projectId);
  const save = useSaveThumbnailIdeas(projectId);
  const make = useMakeThumbnails(projectId);
  const [note, setNote] = useState("");
  const [showIdeas, setShowIdeas] = useState(false);
  const [showOlder, setShowOlder] = useState(false);

  const display = STATUS[thumbnail.status];
  const ideas = data?.ideas ?? null;
  const latest = ideas?.latest ?? null;
  const writing = isJobActive(ideas?.job);
  const all = data?.thumbnails ?? [];
  const makingPictures = all.some((picture) => isJobActive(picture.job));
  const busy = writing || makingPictures;

  // The newest picture of each idea of the newest ideas, in the order of the ideas.
  const ofNewest = latest
    ? all.filter((picture) => picture.concept_version === latest.version)
    : [];
  const newestPerIdea: Thumbnail[] = [];
  const missing: number[] = [];
  (latest?.content.concepts ?? []).forEach((_, index) => {
    const pictures = ofNewest.filter((p) => p.concept_index === index);
    const newest = pictures[0]; // the list is newest first
    if (newest !== undefined) {
      newestPerIdea.push(newest);
    }
    if (!pictures.some((p) => p.has_picture || isJobActive(p.job))) {
      missing.push(index);
    }
  });
  // The chosen thumbnail is always shown, even when it is older or from other ideas.
  const chosen = all.find((picture) => picture.chosen);
  const shown =
    chosen !== undefined && !newestPerIdea.some((p) => p.id === chosen.id)
      ? [...newestPerIdea, chosen]
      : newestPerIdea;
  const older = all.filter((picture) => !shown.some((p) => p.id === picture.id));

  const startIdeas = () => {
    const trimmed = note.trim();
    run.mutate(
      { feedback: trimmed === "" ? null : trimmed },
      { onSuccess: () => setNote("") },
    );
  };

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group gap="xs">
          <Title order={5}>Thumbnails</Title>
          <Badge variant="light" color={display.color}>
            {display.label}
          </Badge>
          {busy && <Loader size="xs" />}
        </Group>
        <Text size="sm" c="dimmed">
          Four pictures are made, one for each idea. The first one that is ready
          is chosen for you, unless you choose another. Upload waits until
          every picture is finished.
        </Text>

        {thumbnail.status === "making" && (
          <Text size="sm" c="dimmed">
            Thumbnails are being made. They are chosen when ready, unless you
            choose another one meanwhile.
          </Text>
        )}
        {thumbnail.status === "none" && !busy && all.length === 0 && (
          <Text size="sm" c="dimmed">
            There are no thumbnails yet. Press Draft for YouTube to make them,
            or write ideas below.
          </Text>
        )}
        {thumbnail.status === "out_of_date" && (
          <Alert color="yellow" title="The chosen thumbnail is out of date">
            <List size="sm">
              {thumbnail.reasons.map((reason) => (
                <List.Item key={reason}>{reason}</List.Item>
              ))}
            </List>
          </Alert>
        )}
        {thumbnail.error !== null && (
          <Alert color="red" title="The last thumbnail attempt failed">
            {thumbnail.error}
          </Alert>
        )}
        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the thumbnails">
            {describeError(error)}
          </Alert>
        )}
        {ideas?.job && ideas.job.status !== "succeeded" && (
          <JobStatusBadge job={ideas.job} />
        )}
        {ideas?.job?.status === "failed" && !writing && (
          <Alert color="red" title="The last ideas run failed">
            {ideas.job.error ?? "The job failed."}
          </Alert>
        )}

        {shown.length > 0 && (
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            {shown.map((picture) => (
              <ThumbnailCard
                key={picture.id}
                projectId={projectId}
                thumbnail={picture}
              />
            ))}
          </SimpleGrid>
        )}

        {older.length > 0 && (
          <Stack gap="xs">
            <Group>
              <Button
                variant="subtle"
                size="compact-sm"
                onClick={() => setShowOlder((open) => !open)}
              >
                {showOlder
                  ? "Hide older pictures"
                  : `Show older pictures (${older.length})`}
              </Button>
            </Group>
            {showOlder && (
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                {older.map((picture) => (
                  <ThumbnailCard
                    key={picture.id}
                    projectId={projectId}
                    thumbnail={picture}
                  />
                ))}
              </SimpleGrid>
            )}
          </Stack>
        )}

        {latest && missing.length > 0 && (
          <Group>
            <Button
              variant="default"
              loading={make.isPending}
              disabled={busy}
              onClick={() =>
                make.mutate({ conceptVersion: latest.version, indexes: missing })
              }
            >
              Make the missing pictures ({missing.length})
            </Button>
          </Group>
        )}
        {make.isError && (
          <Alert color="red" title="Could not start the pictures">
            {describeError(make.error)}
          </Alert>
        )}

        {latest && (
          <Stack gap="xs">
            <Group>
              <Button
                variant="subtle"
                size="compact-sm"
                onClick={() => setShowIdeas((open) => !open)}
              >
                {showIdeas ? "Hide the ideas" : "Edit ideas"}
              </Button>
            </Group>
            {showIdeas && (
              <ThumbnailIdeasEditor
                key={latest.version}
                concepts={latest.content.concepts}
                cast={ideas?.cast ?? []}
                busy={busy}
                saving={save.isPending}
                saveError={save.error}
                making={make.isPending}
                makeError={make.error}
                onSave={(concepts) => save.mutate(concepts)}
                onMake={(indexes) =>
                  make.mutate({ conceptVersion: latest.version, indexes })
                }
              />
            )}
          </Stack>
        )}

        {ideas?.blocked_reason ? (
          <Text size="sm" c="dimmed">
            {ideas.blocked_reason}
          </Text>
        ) : (
          <Stack gap="xs">
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
                variant="default"
                onClick={startIdeas}
                loading={run.isPending || writing}
                disabled={isLoading || isError || makingPictures}
              >
                {latest ? "New ideas" : "Write ideas"}
              </Button>
              <Button
                component={Link}
                to={stepPath(projectId, "thumbnail")}
                variant="subtle"
                size="compact-sm"
              >
                Open in Thumbnails
              </Button>
            </Group>
            {run.isError && (
              <Alert color="red" title="Could not start the thumbnail ideas">
                {describeError(run.error)}
              </Alert>
            )}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
