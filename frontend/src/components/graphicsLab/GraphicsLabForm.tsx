import type { Dispatch, SetStateAction } from "react";
import { Button, Group, SegmentedControl, Stack, Text, Textarea } from "@mantine/core";

import type { GraphicOrientation } from "../../api/graphicsLab";
import {
  LINE_MAX_CHARS,
  ORIENTATION_LABELS,
  formProblem,
  type GraphicsLabFormState,
} from "./graphicsLabView";

type GraphicsLabFormProps = {
  state: GraphicsLabFormState;
  onChange: Dispatch<SetStateAction<GraphicsLabFormState>>;
  onMake: () => void;
  making: boolean;
};

/**
 * The form of the Graphics lab: one line of an explainer script and the orientation. Nothing
 * else is needed (the voice comes in a later phase). Making a run costs nothing: no model is
 * called until the brief is asked for.
 */
export function GraphicsLabForm({ state, onChange, onMake, making }: GraphicsLabFormProps) {
  const problem = formProblem(state);
  const length = state.line.trim().length;

  return (
    <Stack gap="sm">
      <Textarea
        label="The line"
        description="One line of an explainer script. The graphic is made for what it says."
        placeholder="Acme's revenue has exploded. It made 12 billion dollars in 2023, 19 billion in 2024, and 31 billion in 2025."
        value={state.line}
        onChange={(event) => {
          const line = event.currentTarget.value;
          onChange((current) => ({ ...current, line }));
        }}
        autosize
        minRows={3}
        maxRows={8}
        // The server counts the trimmed line, so this only stops a runaway paste.
        maxLength={LINE_MAX_CHARS * 4}
        error={length > LINE_MAX_CHARS ? `The line must be at most ${LINE_MAX_CHARS} characters.` : undefined}
      />
      <Text size="xs" c={length > LINE_MAX_CHARS ? "red" : "dimmed"}>
        {length} of {LINE_MAX_CHARS} characters
      </Text>

      <Group justify="space-between" align="flex-end">
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Orientation
          </Text>
          <SegmentedControl
            value={state.orientation}
            onChange={(value) => {
              const orientation = value as GraphicOrientation;
              onChange((current) => ({ ...current, orientation }));
            }}
            data={(Object.keys(ORIENTATION_LABELS) as GraphicOrientation[]).map((value) => ({
              value,
              label: ORIENTATION_LABELS[value],
            }))}
          />
        </Stack>
        <Button onClick={onMake} loading={making} disabled={problem !== null}>
          Make run
        </Button>
      </Group>
    </Stack>
  );
}
