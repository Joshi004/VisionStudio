import { Alert, Button, Group, Loader, Stack, Text } from "@mantine/core";

import { takeStatus, useCharacterTakes } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { useNow } from "../../hooks/useNow";
import { TakeCard } from "./TakeCard";

/**
 * Everything made with this character, newest first, a page at a time. Takes are never
 * deleted. While one is running the page asks again by itself, and the clock of each running
 * step counts up.
 */
export function TakeGallery({ characterId }: { characterId: number }) {
  const gallery = useCharacterTakes(characterId);
  const takes = gallery.data?.pages.flatMap((page) => page.takes) ?? [];
  const moving = takes.some((take) => takeStatus(take) === "running");
  const now = useNow(moving, gallery.dataUpdatedAt);

  return (
    <Stack gap="md">
      <Text fw={600}>Gallery</Text>
      {gallery.isLoading && <Loader size="sm" />}
      {gallery.isError && (
        <Alert color="red" title="Could not load the gallery">
          {describeError(gallery.error)}
        </Alert>
      )}
      {gallery.data && takes.length === 0 && (
        <Text size="sm" c="dimmed">
          Nothing made with this character yet. Use Create above: what you make appears here, and
          stays.
        </Text>
      )}
      {takes.map((take) => (
        <TakeCard key={take.id} take={take} now={now} />
      ))}
      {gallery.hasNextPage && (
        <Group>
          <Button
            variant="default"
            loading={gallery.isFetchingNextPage}
            onClick={() => void gallery.fetchNextPage()}
          >
            Older
          </Button>
        </Group>
      )}
    </Stack>
  );
}
