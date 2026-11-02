import { useState } from "react";
import { Group, SegmentedControl, Stack, Text, TextInput } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useUpdateGraphicsRender,
  type GraphicRender,
  type GraphicVerdict,
} from "../../api/graphicsLab";

const VERDICTS: { value: GraphicVerdict; label: string }[] = [
  { value: "good", label: "Good" },
  { value: "usable", label: "Usable" },
  { value: "bad", label: "Bad" },
];

/** What you decided after watching a render, and a note to yourself. Saved as soon as you choose. */
export function GraphicsRenderVerdict({ render }: { render: GraphicRender }) {
  const update = useUpdateGraphicsRender();
  const [note, setNote] = useState(render.note ?? "");

  function saveNote() {
    const trimmed = note.trim();
    if (trimmed !== (render.note ?? "")) {
      update.mutate({ renderId: render.id, body: { note: trimmed === "" ? null : trimmed } });
    }
  }

  return (
    <Stack gap={4}>
      <Group gap="xs" wrap="nowrap">
        <SegmentedControl
          size="xs"
          // Nothing is selected while there is no verdict: "none" matches no button.
          value={render.verdict ?? "none"}
          onChange={(value) => {
            // Pressing the chosen button again clears the verdict.
            const verdict = value === render.verdict ? null : (value as GraphicVerdict);
            update.mutate({ renderId: render.id, body: { verdict } });
          }}
          data={[{ value: "none", label: "?", disabled: true }, ...VERDICTS]}
        />
        <TextInput
          size="xs"
          placeholder="A note: what you saw"
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
          onBlur={saveNote}
          maxLength={1000}
          style={{ flex: 1 }}
        />
      </Group>
      {update.isError && (
        <Text size="xs" c="red">
          {describeError(update.error)}
        </Text>
      )}
    </Stack>
  );
}
