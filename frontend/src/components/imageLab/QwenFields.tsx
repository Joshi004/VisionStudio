import { Button, Group, SegmentedControl, Select, Stack, Text, TextInput, Textarea } from "@mantine/core";

import {
  blockedReason,
  QWEN_MODE_LABELS,
  QWEN_MODE_NOTE,
  QWEN_SHAPES,
  type LabFormState,
  type QwenMode,
  type QwenShape,
} from "./labView";

type QwenFieldsProps = {
  state: LabFormState;
  onChange: (update: (current: LabFormState) => LabFormState) => void;
  onRun: () => void;
  /** True while the start request is on its way. The run itself continues without the form. */
  starting: boolean;
};

/**
 * The form of one Qwen-Image-2.1 run: text to image on your GPU server. A run is a job that takes
 * minutes, so pressing Run only starts it: it shows below while it works, and in the history.
 * Several can be started one after another.
 */
export function QwenFields({ state, onChange, onRun, starting }: QwenFieldsProps) {
  function set<K extends keyof LabFormState>(key: K, value: LabFormState[K]) {
    onChange((current) => ({ ...current, [key]: value }));
  }

  const blocked = blockedReason(state);
  const quality = state.qwenMode === "quality";

  return (
    <Stack gap="md">
      <Textarea
        label="Prompt"
        description="Write complete sentences and be specific: the subject, the setting, where things sit in the frame, the camera, the light. The model has no negative prompt, and it draws any words you put in quotes."
        value={state.prompt}
        onChange={(event) => set("prompt", event.currentTarget.value)}
        autosize
        minRows={5}
        maxRows={16}
      />

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Mode
        </Text>
        <SegmentedControl
          value={state.qwenMode}
          onChange={(value) => set("qwenMode", value as QwenMode)}
          data={(Object.keys(QWEN_MODE_LABELS) as QwenMode[]).map((mode) => ({
            value: mode,
            label: QWEN_MODE_LABELS[mode],
          }))}
        />
        <Text size="xs" c="dimmed">
          {QWEN_MODE_NOTE}
        </Text>
      </Stack>

      <Group align="flex-start" grow>
        <Select
          label="Shape"
          description="The model makes these seven shapes only."
          data={QWEN_SHAPES}
          value={state.aspectRatio}
          onChange={(value) => set("aspectRatio", (value ?? "9:16") as QwenShape)}
          allowDeselect={false}
        />
        <TextInput
          label="Seed"
          description="Empty: a random seed."
          placeholder="42"
          inputMode="numeric"
          value={state.seed}
          onChange={(event) => set("seed", event.currentTarget.value)}
        />
        <TextInput
          label="Steps"
          description={quality ? "Empty: the server's own (40)." : "Quality mode only."}
          placeholder="40"
          inputMode="numeric"
          value={quality ? state.steps : ""}
          onChange={(event) => set("steps", event.currentTarget.value)}
          disabled={!quality}
        />
      </Group>

      <Group gap="sm" align="center">
        <Button onClick={onRun} disabled={blocked !== null} loading={starting} size="md">
          Run on the GPU server
        </Button>
        <Text size="sm" c="dimmed">
          {blocked ?? "Takes a few minutes. You can leave this page: the image appears below and in the history."}
        </Text>
      </Group>
      <Text size="xs" c="dimmed">
        Runs on your GPU server, so there is no price per image. Each run loads the model first,
        and the server runs a couple at a time. The license is non-commercial (Qwen Research
        License).
      </Text>
    </Stack>
  );
}
