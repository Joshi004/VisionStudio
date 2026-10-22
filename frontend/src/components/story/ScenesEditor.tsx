import { useState } from "react";
import { Button, Group, Paper, Stack, Text, TextInput, Textarea } from "@mantine/core";

import type { SceneInput, SceneItem } from "../../api/scenes";
import { EditorActions } from "./editorParts";
import { slugFromName } from "./slugFromName";

type ScenesEditorProps = {
  /** The newest list of scenes; the form starts from it. */
  initial: SceneItem[];
  saving: boolean;
  error: unknown;
  onSave: (scenes: SceneInput[]) => void;
  onCancel: () => void;
};

/** A row being edited. Rows that were already saved keep their id: the later stages use it. */
type Row = SceneInput & { isNew: boolean; idTouched: boolean };

/**
 * The list of scenes as a form. A scene is its title, a note, and the first words of the slice
 * of the story it owns: the slices are cut where each scene's opening words are found, so the
 * first scene must open with the first words of the story. The server checks the opening words
 * against the saved story and says which scene is wrong.
 */
export function ScenesEditor({ initial, saving, error, onSave, onCancel }: ScenesEditorProps) {
  const [rows, setRows] = useState<Row[]>(
    initial.map((scene) => ({
      id: scene.id,
      title: scene.title,
      description: scene.description,
      starts_with: scene.starts_with,
      isNew: false,
      idTouched: true,
    })),
  );

  const change = (index: number, part: Partial<Row>) =>
    setRows(rows.map((row, position) => (position === index ? { ...row, ...part } : row)));

  const changeTitle = (index: number, title: string) => {
    const row = rows[index];
    if (row.isNew && !row.idTouched) {
      const taken = rows.filter((_, position) => position !== index).map((item) => item.id);
      change(index, { title, id: slugFromName(title, taken) });
    } else {
      change(index, { title });
    }
  };

  const addRow = () =>
    setRows([
      ...rows,
      { id: "", title: "", description: "", starts_with: "", isNew: true, idTouched: false },
    ]);

  return (
    <Stack gap="sm">
      {rows.map((row, index) => (
        <Paper key={index} withBorder p="sm" radius="sm">
          <Stack gap="xs">
            <Group gap="xs" align="flex-end" wrap="nowrap">
              <TextInput
                label={`Scene ${index + 1} title`}
                value={row.title}
                onChange={(event) => changeTitle(index, event.currentTarget.value)}
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
                aria-label={`Remove scene ${index + 1}`}
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
            <TextInput
              label="Opening words"
              description="The first five to ten words of this scene, copied exactly from the story."
              value={row.starts_with}
              onChange={(event) => change(index, { starts_with: event.currentTarget.value })}
            />
          </Stack>
        </Paper>
      ))}
      {rows.length === 0 && (
        <Text size="sm" c="dimmed">
          No scenes. Add one.
        </Text>
      )}
      <Group>
        <Button variant="default" onClick={addRow}>
          Add a scene
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        Saving adds a new version written by you. The stages after it will say they are out of
        date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the scenes"
        onSave={() =>
          onSave(
            rows.map((row) => ({
              id: row.id,
              title: row.title,
              description: row.description,
              starts_with: row.starts_with,
            })),
          )
        }
        onCancel={onCancel}
      />
    </Stack>
  );
}
