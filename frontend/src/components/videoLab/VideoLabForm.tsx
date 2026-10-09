import {
  Alert,
  Button,
  Checkbox,
  Group,
  NumberInput,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import { VIDEO_MODELS, videoModelLabel, type VideoModel } from "../../videoModels";
import { FirstFramePicker } from "./FirstFramePicker";
import { labPromptHints } from "./labPromptHints";
import { PromptHelper } from "./PromptHelper";
import {
  costText,
  DURATION_MAX_S,
  DURATION_MIN_S,
  durationOf,
  formProblem,
  type VideoLabFormState,
} from "./videoLabView";

type VideoLabFormProps = {
  state: VideoLabFormState;
  onChange: (state: VideoLabFormState) => void;
  onRun: () => void;
  running: boolean;
};

function runLabel(models: VideoModel[]): string {
  if (models.length === 2) {
    return "Run on both models";
  }
  return models.length === 1 ? `Run on ${videoModelLabel(models[0])}` : "Run";
}

/**
 * The Video lab's form: the prompt, the model or models, the recipe, the shape and length of
 * the clip, the seed and an optional first frame. Two models make two runs that differ only
 * by the model: the same prompt, first frame, size, length, recipe and seed.
 */
export function VideoLabForm({ state, onChange, onRun, running }: VideoLabFormProps) {
  const problem = formProblem(state);
  const duration = durationOf(state);
  const hints = labPromptHints({ prompt: state.prompt, durationS: duration, models: state.models });
  const has23 = state.models.includes("ltx-2.3");

  function update(changes: Partial<VideoLabFormState>) {
    onChange({ ...state, ...changes });
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (problem === null) {
          onRun();
        }
      }}
    >
      <Stack gap="md">
        <Checkbox.Group
          label="Models"
          description="Choose both to compare them: the two clips differ only by the model."
          value={state.models}
          onChange={(value) =>
            update({
              models: VIDEO_MODELS.map((entry) => entry.value).filter((model) =>
                value.includes(model),
              ),
            })
          }
        >
          <Group gap="lg" mt={6}>
            {VIDEO_MODELS.map((entry) => (
              <Checkbox key={entry.value} value={entry.value} label={entry.label} />
            ))}
          </Group>
        </Checkbox.Group>

        <Group align="flex-start" gap="md">
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Recipe
            </Text>
            <SegmentedControl
              value={state.mode}
              onChange={(value) => update({ mode: value === "fast" ? "fast" : "quality" })}
              data={[
                { value: "quality", label: "Quality" },
                { value: "fast", label: "Fast" },
              ]}
            />
            <Text size="xs" c="dimmed" maw={260}>
              Quality is sharper and slower. LTX-2.5 quality is the DFR recipe.
            </Text>
          </Stack>
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Shape
            </Text>
            <SegmentedControl
              value={state.orientation}
              onChange={(value) =>
                update({ orientation: value === "landscape" ? "landscape" : "portrait" })
              }
              data={[
                { value: "portrait", label: "Portrait 1088 x 1920" },
                { value: "landscape", label: "Landscape 1920 x 1088" },
              ]}
            />
          </Stack>
          <NumberInput
            label="Length (seconds)"
            description={`${DURATION_MIN_S} to ${DURATION_MAX_S}. 24 fps.`}
            value={state.durationS}
            onChange={(value) => update({ durationS: value })}
            min={DURATION_MIN_S}
            max={DURATION_MAX_S}
            step={1}
            decimalScale={1}
            allowNegative={false}
            clampBehavior="none"
            w={170}
          />
          <TextInput
            label="Seed"
            description="Empty: random. Both runs share it."
            value={state.seed}
            onChange={(event) => update({ seed: event.currentTarget.value })}
            w={190}
          />
        </Group>

        <FirstFramePicker
          value={state.firstFrame}
          onChange={(firstFrame) => update({ firstFrame })}
        />

        <PromptHelper
          durationS={duration}
          hasFirstFrame={state.firstFrame !== null}
          onUse={(prompt) => update({ prompt })}
        />

        <Stack gap={4}>
          <Textarea
            label="Prompt"
            description="One paragraph, present tense. For LTX-2.5 cuts, name each transition in a sentence."
            value={state.prompt}
            onChange={(event) => update({ prompt: event.currentTarget.value })}
            autosize
            minRows={5}
            maxLength={8000}
          />
          {hints.map((hint) => (
            <Text key={hint} size="xs" c="orange.8">
              {hint}
            </Text>
          ))}
        </Stack>

        <Textarea
          label="Negative prompt (LTX-2.3 only)"
          description="Empty: the GPU server's own default negative prompt. LTX-2.5 has no negative prompt and is sent none."
          value={state.negativePrompt}
          onChange={(event) => update({ negativePrompt: event.currentTarget.value })}
          disabled={!has23}
          autosize
          minRows={2}
          maxLength={2000}
        />

        <Stack gap={6} align="flex-start">
          <Button type="submit" loading={running} disabled={problem !== null}>
            {runLabel(state.models)}
          </Button>
          {problem !== null && state.prompt.trim() !== "" && (
            <Alert color="yellow" p="xs">
              {problem}
            </Alert>
          )}
          {state.models.length > 0 && (
            <Text size="xs" c="dimmed">
              {costText(state.models.length)} A run starts only when you press the button.
            </Text>
          )}
        </Stack>
      </Stack>
    </form>
  );
}
