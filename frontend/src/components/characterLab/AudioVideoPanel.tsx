import type { Dispatch, SetStateAction } from "react";
import { Alert, Button, Group, Loader, Stack, Text } from "@mantine/core";

import { avTestIsMoving, useAvTests } from "../../api/avLab";
import type { LibraryCharacter } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { useNow } from "../../hooks/useNow";
import { AvTestCard } from "./AvTestCard";
import { AvTestForm } from "./AvTestForm";
import type { AvFormState } from "./avLabView";

type AudioVideoPanelProps = {
  character: LibraryCharacter;
  /** The form lives in the page, so switching to the takes and back keeps what was typed. */
  form: AvFormState;
  onChange: Dispatch<SetStateAction<AvFormState>>;
};

/**
 * The Audio video lab of one character: a form to make a test, and the tests made, newest first.
 * A test is never deleted. While one is moving along, the page asks again by itself.
 */
export function AudioVideoPanel({ character, form, onChange }: AudioVideoPanelProps) {
  const tests = useAvTests(character.id);
  const list = tests.data?.pages.flatMap((page) => page.tests) ?? [];
  const moving = list.some(avTestIsMoving);
  const now = useNow(moving, tests.dataUpdatedAt);

  return (
    <Stack gap="lg">
      <AvTestForm character={character} form={form} onChange={onChange} />
      <Stack gap="md">
        <Text fw={600}>Tests</Text>
        {tests.isLoading && <Loader size="sm" />}
        {tests.isError && (
          <Alert color="red" title="Could not load the tests">
            {describeError(tests.error)}
          </Alert>
        )}
        {tests.data && list.length === 0 && (
          <Text size="sm" c="dimmed">
            No test yet. Write a text above, mark the parts to show as video and press Make the
            test: it appears here, and stays.
          </Text>
        )}
        {list.map((test) => (
          <AvTestCard key={test.id} test={test} now={now} />
        ))}
        {tests.hasNextPage && (
          <Group>
            <Button
              variant="default"
              loading={tests.isFetchingNextPage}
              onClick={() => void tests.fetchNextPage()}
            >
              Older
            </Button>
          </Group>
        )}
      </Stack>
    </Stack>
  );
}
