import { useState } from "react";
import { Button, Group, Paper, Select, Stack, Text, TextInput, Textarea } from "@mantine/core";

import type { SceneEvent, SceneEventInput } from "../../api/sceneEvents";
import { EditorActions } from "./editorParts";

type SceneEventsEditorProps = {
  /** The scene's newest events; the form starts from them. */
  initial: SceneEvent[];
  /** The story's characters, for who speaks a line. */
  characters: { id: string; name: string }[];
  saving: boolean;
  error: unknown;
  onSave: (events: SceneEventInput[]) => void;
  onCancel: () => void;
};

type EventType = SceneEventInput["type"];

const TYPE_OPTIONS: { value: EventType; label: string }[] = [
  { value: "narration", label: "Narration" },
  { value: "dialogue", label: "Dialogue" },
  { value: "action", label: "Action" },
  { value: "sound_event", label: "Sound" },
  { value: "pause", label: "Pause" },
];

/** A row being edited. Every field is kept while the type changes; only the type's own are sent. */
type Row = {
  type: EventType;
  text: string;
  speaker_id: string | null;
  emotion: string;
  description: string;
};

function toRow(event: SceneEvent): Row {
  return {
    type: event.type,
    text: event.text ?? "",
    speaker_id: event.speaker_id ?? null,
    emotion: event.delivery?.emotion ?? "",
    description: event.description ?? "",
  };
}

/** The fields of the row's type. The server sets the ids from the order. */
function toInput(row: Row): SceneEventInput {
  switch (row.type) {
    case "narration":
      return { type: "narration", text: row.text };
    case "dialogue":
      return {
        type: "dialogue",
        speaker_id: row.speaker_id,
        text: row.text,
        ...(row.emotion.trim() !== "" ? { delivery: { emotion: row.emotion } } : {}),
      };
    case "action":
    case "sound_event":
      return { type: row.type, description: row.description };
    case "pause":
      return { type: "pause" };
  }
}

/**
 * One scene's events as a structured form: the type of each event, the words of a narration or
 * a line, who speaks it, and the description of an action or a sound. The order can be changed.
 * The server checks that the spoken words come from the scene's text, in order, and says which
 * event is wrong. The ids (`evt_1`, ...) are set from the order.
 */
export function SceneEventsEditor({
  initial,
  characters,
  saving,
  error,
  onSave,
  onCancel,
}: SceneEventsEditorProps) {
  const [rows, setRows] = useState<Row[]>(initial.map(toRow));

  const change = (index: number, part: Partial<Row>) =>
    setRows(rows.map((row, position) => (position === index ? { ...row, ...part } : row)));

  const move = (index: number, step: -1 | 1) => {
    const target = index + step;
    if (target < 0 || target >= rows.length) {
      return;
    }
    const next = [...rows];
    [next[index], next[target]] = [next[target], next[index]];
    setRows(next);
  };

  const speakerOptions = [
    ...characters.map((item) => ({ value: item.id, label: `${item.name} (${item.id})` })),
    ...rows
      .map((row) => row.speaker_id)
      .filter((id): id is string => id !== null && !characters.some((item) => item.id === id))
      .map((id) => ({ value: id, label: id })),
  ];

  return (
    <Stack gap="sm">
      {rows.map((row, index) => (
        <Paper key={index} withBorder p="sm" radius="sm">
          <Stack gap="xs">
            <Group gap="xs" align="flex-end" wrap="nowrap">
              <Select
                label={`Event ${index + 1}`}
                data={TYPE_OPTIONS}
                value={row.type}
                allowDeselect={false}
                onChange={(value) => value !== null && change(index, { type: value as EventType })}
                w={160}
              />
              {row.type === "dialogue" && (
                <Select
                  label="Speaker"
                  placeholder="Who speaks"
                  data={speakerOptions}
                  value={row.speaker_id}
                  searchable
                  onChange={(value) => change(index, { speaker_id: value })}
                  style={{ flex: 1 }}
                />
              )}
              <Group gap={4} wrap="nowrap" ml="auto">
                <Button
                  variant="default"
                  aria-label={`Move event ${index + 1} up`}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  Up
                </Button>
                <Button
                  variant="default"
                  aria-label={`Move event ${index + 1} down`}
                  disabled={index === rows.length - 1}
                  onClick={() => move(index, 1)}
                >
                  Down
                </Button>
                <Button
                  variant="default"
                  aria-label={`Remove event ${index + 1}`}
                  onClick={() => setRows(rows.filter((_, position) => position !== index))}
                >
                  Remove
                </Button>
              </Group>
            </Group>
            {(row.type === "narration" || row.type === "dialogue") && (
              <Textarea
                label="Words"
                description="Copied from the scene's text; not shortened or changed."
                autosize
                minRows={2}
                value={row.text}
                onChange={(event) => change(index, { text: event.currentTarget.value })}
              />
            )}
            {row.type === "dialogue" && (
              <TextInput
                label="How it is said"
                description="Optional: a short phrase such as “whispering”."
                value={row.emotion}
                onChange={(event) => change(index, { emotion: event.currentTarget.value })}
              />
            )}
            {(row.type === "action" || row.type === "sound_event") && (
              <TextInput
                label="Description"
                description="One plain sentence."
                value={row.description}
                onChange={(event) => change(index, { description: event.currentTarget.value })}
              />
            )}
            {row.type === "pause" && (
              <Text size="xs" c="dimmed">
                A meaningful silence at this point. It has no other fields.
              </Text>
            )}
          </Stack>
        </Paper>
      ))}
      {rows.length === 0 && (
        <Text size="sm" c="dimmed">
          No events. Add one.
        </Text>
      )}
      <Group>
        <Button
          variant="default"
          onClick={() =>
            setRows([
              ...rows,
              { type: "narration", text: "", speaker_id: null, emotion: "", description: "" },
            ])
          }
        >
          Add an event
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        Saving adds a new version written by you. The speech units after it will say they are out
        of date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the scene events"
        onSave={() => onSave(rows.map(toInput))}
        onCancel={onCancel}
      />
    </Stack>
  );
}
