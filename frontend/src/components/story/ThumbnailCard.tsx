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
  Stack,
  Text,
  TextInput,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useChooseThumbnail,
  useMakeThumbnails,
  useSetThumbnailHeadline,
  type Thumbnail,
} from "../../api/thumbnails";
import { JobStatusBadge } from "../jobs/JobStatusBadge";

type ThumbnailCardProps = {
  projectId: number;
  thumbnail: Thumbnail;
};

/**
 * One picture with its headline, a way to change the headline, choose it, make it again and
 * download it. Used by the Thumbnails panel and by the Publish panel.
 */
export function ThumbnailCard({ projectId, thumbnail }: ThumbnailCardProps) {
  const setHeadline = useSetThumbnailHeadline(projectId);
  const choose = useChooseThumbnail(projectId);
  const makeAgain = useMakeThumbnails(projectId);
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
          </>
        )}

        <Group gap="xs">
          {thumbnail.has_picture && (
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
          )}
          {!active && (
            <Button
              variant="default"
              onClick={() =>
                makeAgain.mutate({
                  conceptVersion: thumbnail.concept_version,
                  indexes: [thumbnail.concept_index],
                })
              }
              loading={makeAgain.isPending}
            >
              Make again
            </Button>
          )}
          {thumbnail.has_picture && thumbnail.url && (
            <Button
              component="a"
              href={thumbnail.url}
              download={`thumbnail-${thumbnail.id}.png`}
              variant="default"
            >
              Download
            </Button>
          )}
          {thumbnail.has_picture && thumbnail.width && thumbnail.height && (
            <Text size="xs" c="dimmed">
              {thumbnail.width} x {thumbnail.height}
            </Text>
          )}
        </Group>
        {makeAgain.isError && (
          <Alert color="red" title="Could not make the picture again">
            {describeError(makeAgain.error)}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
