import { useState } from "react";
import { Alert, Button, Group, Select, Stack, Text, TextInput } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useResetContractSources,
  useSaveContractSources,
  type ContractSources,
} from "../../api/gpu";
import {
  BASE_OPTIONS,
  MAX_SOURCES,
  isUnchanged,
  newSourceDraft,
  toDraft,
  toRequest,
  type SourceDraft,
} from "./contractDraft";

/**
 * The list of addresses whose answers are recorded and checked. The section
 * gives this component a key made from the saved list, so the draft starts
 * again from the new value after every save or reset.
 */
export function ContractSourcesEditor({ saved }: { saved: ContractSources }) {
  const [draft, setDraft] = useState<SourceDraft[]>(() => toDraft(saved));
  const save = useSaveContractSources();
  const reset = useResetContractSources();

  const errorMessage = save.isError
    ? describeError(save.error)
    : reset.isError
      ? describeError(reset.error)
      : undefined;

  function changeDraft(next: SourceDraft[]) {
    setDraft(next);
    save.reset();
    reset.reset();
  }

  function changeRow(id: number, change: Partial<Omit<SourceDraft, "id">>) {
    changeDraft(draft.map((item) => (item.id === id ? { ...item, ...change } : item)));
  }

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Each source is an address on one of your servers whose JSON answer is recorded. A source is
        approved by its name and path, so changing a path means it needs approval again.
      </Text>

      {draft.map((item) => (
        <Group key={item.id} align="flex-end" wrap="nowrap" gap="xs">
          <TextInput
            label="Name"
            value={item.name}
            onChange={(event) => changeRow(item.id, { name: event.currentTarget.value })}
            w={150}
          />
          <Select
            label="Server"
            data={BASE_OPTIONS}
            value={item.base}
            allowDeselect={false}
            onChange={(value) => {
              if (value === "gpu" || value === "transcription") {
                changeRow(item.id, { base: value });
              }
            }}
            w={190}
          />
          <TextInput
            label="Path"
            value={item.path}
            onChange={(event) => changeRow(item.id, { path: event.currentTarget.value })}
            style={{ flex: 1 }}
          />
          <Button
            variant="default"
            onClick={() => changeDraft(draft.filter((other) => other.id !== item.id))}
            disabled={draft.length <= 1}
          >
            Remove
          </Button>
        </Group>
      ))}

      {saved.note && (
        <Text size="xs" c="orange">
          {saved.note}
        </Text>
      )}
      {errorMessage && (
        <Alert color="red" title="Could not save the sources">
          {errorMessage}
        </Alert>
      )}

      <Group gap="xs">
        <Button
          variant="default"
          onClick={() => changeDraft([...draft, newSourceDraft()])}
          disabled={draft.length >= MAX_SOURCES}
        >
          Add source
        </Button>
        <Button
          onClick={() => save.mutate(toRequest(draft))}
          disabled={isUnchanged(draft, saved) || reset.isPending}
          loading={save.isPending}
        >
          Save
        </Button>
        {saved.source === "saved" && (
          <Button
            variant="default"
            onClick={() => reset.mutate()}
            disabled={save.isPending}
            loading={reset.isPending}
          >
            Reset to defaults
          </Button>
        )}
      </Group>

      <Stack gap={2}>
        {saved.sources.map((item) => (
          <Text key={item.name} size="xs" c="dimmed">
            {item.name} will call: {item.called_url}
          </Text>
        ))}
      </Stack>
    </Stack>
  );
}
