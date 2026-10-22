import { useState } from "react";
import { Button, Group, Paper, Stack, Text, TextInput, Textarea } from "@mantine/core";

import type { DiscoveryItem, DiscoveryItemInput } from "../../api/discovery";
import { EditorActions } from "./editorParts";
import { slugFromName } from "./slugFromName";

type DiscoveryListEditorProps = {
  /** What one row is, in the singular and lower case: "character", "environment". */
  noun: string;
  /** The newest list; the form starts from it. */
  initial: DiscoveryItem[];
  saving: boolean;
  error: unknown;
  onSave: (items: DiscoveryItemInput[]) => void;
  onCancel: () => void;
};

/** A row being edited. Rows that were already saved keep their id: the later stages use it. */
type Row = DiscoveryItemInput & { isNew: boolean; idTouched: boolean };

/**
 * The list of characters or environments as a form: change the names and notes, add rows, remove
 * rows. The server refuses to remove one that a scene uses, and says which scenes.
 */
export function DiscoveryListEditor({
  noun,
  initial,
  saving,
  error,
  onSave,
  onCancel,
}: DiscoveryListEditorProps) {
  const [rows, setRows] = useState<Row[]>(
    initial.map((item) => ({
      id: item.id,
      name: item.name,
      description: item.description,
      isNew: false,
      idTouched: true,
    })),
  );

  const change = (index: number, part: Partial<Row>) =>
    setRows(rows.map((row, position) => (position === index ? { ...row, ...part } : row)));

  const changeName = (index: number, name: string) => {
    const row = rows[index];
    if (row.isNew && !row.idTouched) {
      const taken = rows.filter((_, position) => position !== index).map((item) => item.id);
      change(index, { name, id: slugFromName(name, taken) });
    } else {
      change(index, { name });
    }
  };

  const addRow = () =>
    setRows([...rows, { id: "", name: "", description: "", isNew: true, idTouched: false }]);

  return (
    <Stack gap="sm">
      {rows.map((row, index) => (
        <Paper key={index} withBorder p="sm" radius="sm">
          <Stack gap="xs">
            <Group gap="xs" align="flex-end" wrap="nowrap">
              <TextInput
                label="Name"
                value={row.name}
                onChange={(event) => changeName(index, event.currentTarget.value)}
                style={{ flex: 1 }}
              />
              <TextInput
                label="Id"
                description={row.isNew ? "Lower case, no spaces" : undefined}
                value={row.id}
                readOnly={!row.isNew}
                disabled={!row.isNew}
                onChange={(event) =>
                  change(index, { id: event.currentTarget.value, idTouched: true })
                }
                w={200}
              />
              <Button
                variant="default"
                aria-label={`Remove this ${noun}`}
                onClick={() => setRows(rows.filter((_, position) => position !== index))}
              >
                Remove
              </Button>
            </Group>
            <Textarea
              label="Description"
              autosize
              minRows={2}
              value={row.description}
              onChange={(event) => change(index, { description: event.currentTarget.value })}
            />
          </Stack>
        </Paper>
      ))}
      {rows.length === 0 && (
        <Text size="sm" c="dimmed">
          No {noun}s. Add one.
        </Text>
      )}
      <Group>
        <Button variant="default" onClick={addRow}>
          Add a {noun}
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        Saving adds a new version written by you. The stages after it will say they are out of
        date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle={`Could not save the ${noun}s`}
        onSave={() =>
          onSave(rows.map((row) => ({ id: row.id, name: row.name, description: row.description })))
        }
        onCancel={onCancel}
      />
    </Stack>
  );
}
