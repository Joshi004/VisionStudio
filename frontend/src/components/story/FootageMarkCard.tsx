import { useState } from "react";
import { Alert, Badge, Button, Group, Paper, Select, Stack, Text, TextInput } from "@mantine/core";

import { FOOTAGE_KINDS, type FootageMark, type FootageMarkEdit } from "../../api/footageMarks";

type Props = {
  mark: FootageMark;
  active?: boolean;
  busy: boolean;
  onSelect?: () => void;
  onEdit: (edit: FootageMarkEdit) => void;
  onRemove: () => void;
};

/** One footage mark: its words, where it came from, its kind and the note on what to show. */
export function FootageMarkCard({ mark, active = false, busy, onSelect, onEdit, onRemove }: Props) {
  const [note, setNote] = useState(mark.note);
  const isOwner = mark.origin === "owner";
  const dropped = mark.kept === false;
  return (
    <Paper
      withBorder
      p="sm"
      radius="sm"
      onClick={onSelect}
      style={{ borderColor: active ? "var(--mantine-color-blue-filled)" : undefined }}
    >
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Badge color={isOwner ? "orange" : "blue"} variant="light">
              {isOwner ? "You" : "GLM"}
            </Badge>
            {mark.origin === "glm" && mark.kept === null && (
              <Badge color="gray" variant="outline">
                To decide
              </Badge>
            )}
            {dropped && (
              <Badge color="gray" variant="outline">
                Dropped
              </Badge>
            )}
            <Text size="sm" fw={500} style={{ whiteSpace: "pre-wrap" }}>
              {mark.text}
            </Text>
          </Group>
          <Group gap="xs" wrap="nowrap">
            {isOwner ? (
              <Button size="compact-sm" variant="default" onClick={onRemove} disabled={busy}>
                Remove
              </Button>
            ) : (
              <>
                {mark.kept !== true && (
                  <Button
                    size="compact-sm"
                    onClick={() => onEdit({ kept: true })}
                    disabled={busy || mark.words_changed}
                  >
                    {dropped ? "Keep again" : "Keep"}
                  </Button>
                )}
                {mark.kept !== false && (
                  <Button
                    size="compact-sm"
                    variant="default"
                    onClick={() => onEdit({ kept: false })}
                    disabled={busy}
                  >
                    Drop
                  </Button>
                )}
              </>
            )}
          </Group>
        </Group>
        {mark.reason !== "" && (
          <Text size="xs" c="dimmed">
            {mark.reason}
          </Text>
        )}
        {mark.words_changed && !dropped && (
          <Alert color="yellow" p="xs">
            {isOwner
              ? "The words of this mark are no longer in the story. Remove it and mark the new words."
              : "The words of this proposal are no longer in the story. Drop it."}
          </Alert>
        )}
        {!dropped && (
          <Group gap="xs" wrap="nowrap" onClick={(event) => event.stopPropagation()}>
            <Select
              size="xs"
              w={120}
              aria-label="Kind of footage"
              data={FOOTAGE_KINDS.map((kind) => ({ value: kind.value, label: kind.label }))}
              value={mark.kind_hint}
              allowDeselect={false}
              disabled={busy}
              onChange={(value) => {
                const kind = FOOTAGE_KINDS.find((item) => item.value === value);
                if (kind && kind.value !== mark.kind_hint) {
                  onEdit({ kind_hint: kind.value });
                }
              }}
            />
            <TextInput
              size="xs"
              style={{ flex: 1 }}
              aria-label="What should the viewer see?"
              placeholder="What should the viewer see? (optional)"
              maxLength={300}
              value={note}
              disabled={busy}
              onChange={(event) => setNote(event.currentTarget.value)}
              onBlur={() => {
                if (note !== mark.note) {
                  onEdit({ note });
                }
              }}
            />
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
