import { useState } from "react";
import { Badge, Button, Group, Paper, Stack, Text, Textarea } from "@mantine/core";

import type { SpeechUnit, SpeechUnitInput } from "../../api/speechUnits";
import { EditorActions } from "./editorParts";

type SpeechUnitsEditorProps = {
  /** The scene's newest speech units; the form starts from them. */
  initial: SpeechUnit[];
  characterNames: Record<string, string>;
  saving: boolean;
  error: unknown;
  onSave: (units: SpeechUnitInput[]) => void;
  onCancel: () => void;
};

/** The parts of one event's words, in order. */
type EventParts = {
  eventId: string;
  kind: SpeechUnit["kind"];
  speakerId: string | null;
  parts: string[];
};

function toGroups(units: SpeechUnit[]): EventParts[] {
  const groups: EventParts[] = [];
  for (const unit of [...units].sort((a, b) => a.order - b.order)) {
    const group = groups.find((item) => item.eventId === unit.event_id);
    if (group === undefined) {
      groups.push({
        eventId: unit.event_id,
        kind: unit.kind,
        speakerId: unit.speaker_id,
        parts: [unit.text],
      });
    } else {
      group.parts.push(unit.text);
    }
  }
  return groups;
}

/**
 * One scene's speech units, re-split by hand. Each event's words are shown as parts: move the
 * cut by editing the parts, split a part where the cursor is, or merge a part with the next. The
 * words themselves cannot change: the server refuses a save when the parts, joined, are not
 * exactly the event's words. A part that is too long is only a warning, not a refusal.
 */
export function SpeechUnitsEditor({
  initial,
  characterNames,
  saving,
  error,
  onSave,
  onCancel,
}: SpeechUnitsEditorProps) {
  const [groups, setGroups] = useState<EventParts[]>(toGroups(initial));
  // Where the cursor is in a part, by group and part, for "Split here".
  const [cursors, setCursors] = useState<Record<string, number>>({});

  const setParts = (index: number, parts: string[]) =>
    setGroups(groups.map((group, position) => (position === index ? { ...group, parts } : group)));

  const split = (groupIndex: number, partIndex: number) => {
    const parts = groups[groupIndex].parts;
    const text = parts[partIndex];
    const cursor = cursors[`${groupIndex}-${partIndex}`] ?? 0;
    const left = text.slice(0, cursor).trim();
    const right = text.slice(cursor).trim();
    if (left === "" || right === "") {
      return;
    }
    setParts(groupIndex, [
      ...parts.slice(0, partIndex),
      left,
      right,
      ...parts.slice(partIndex + 1),
    ]);
  };

  const merge = (groupIndex: number, partIndex: number) => {
    const parts = groups[groupIndex].parts;
    const joined = `${parts[partIndex]} ${parts[partIndex + 1]}`.trim();
    setParts(groupIndex, [
      ...parts.slice(0, partIndex),
      joined,
      ...parts.slice(partIndex + 2),
    ]);
  };

  return (
    <Stack gap="sm">
      {groups.map((group, groupIndex) => (
        <Paper key={group.eventId} withBorder p="sm" radius="sm">
          <Stack gap="xs">
            <Group gap="xs">
              <Badge variant="light" color={group.kind === "dialogue" ? "blue" : "gray"}>
                {group.kind}
              </Badge>
              {group.speakerId !== null && (
                <Text size="sm" fw={500}>
                  {characterNames[group.speakerId] ?? group.speakerId}
                </Text>
              )}
            </Group>
            {group.parts.map((part, partIndex) => (
              <Group key={partIndex} gap="xs" align="flex-start" wrap="nowrap">
                <Textarea
                  aria-label={`Part ${partIndex + 1}`}
                  autosize
                  minRows={1}
                  value={part}
                  onChange={(event) =>
                    setParts(
                      groupIndex,
                      group.parts.map((text, position) =>
                        position === partIndex ? event.currentTarget.value : text,
                      ),
                    )
                  }
                  onSelect={(event) => {
                    const cursor = event.currentTarget.selectionStart;
                    setCursors((current) => ({
                      ...current,
                      [`${groupIndex}-${partIndex}`]: cursor,
                    }));
                  }}
                  style={{ flex: 1 }}
                />
                <Stack gap={4}>
                  <Button
                    size="compact-xs"
                    variant="default"
                    title="Cut this part where the cursor is"
                    onClick={() => split(groupIndex, partIndex)}
                  >
                    Split here
                  </Button>
                  {partIndex < group.parts.length - 1 && (
                    <Button
                      size="compact-xs"
                      variant="default"
                      title="Join this part with the next one"
                      onClick={() => merge(groupIndex, partIndex)}
                    >
                      Merge with next
                    </Button>
                  )}
                </Stack>
              </Group>
            ))}
          </Stack>
        </Paper>
      ))}
      <Text size="xs" c="dimmed">
        Saving adds a new plan written by you. The speech made for the old units will say it is out
        of date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the speech units"
        onSave={() =>
          onSave(
            groups.flatMap((group) =>
              group.parts.map((text) => ({ event_id: group.eventId, text })),
            ),
          )
        }
        onCancel={onCancel}
      />
    </Stack>
  );
}
