import {
  Alert,
  Button,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import type { Voice } from "../../api/voiceLab";
import { LicenseNotice } from "./LicenseNotice";
import {
  CFG_SCALE_MAX,
  formProblem,
  INSTRUCTION_MAX_CHARS,
  MODES,
  needsVoice,
  takesInstruction,
  TEXT_MAX_CHARS,
  type VoiceLabFormState,
  type VoiceMode,
} from "./voiceLabView";

type VoiceLabFormProps = {
  state: VoiceLabFormState;
  onChange: (state: VoiceLabFormState) => void;
  onRun: () => void;
  running: boolean;
  voices: Voice[];
};

/**
 * The Voice lab's form: the mode, the saved voice (clone and direction), the text, the
 * instruction, the seed and the guidance. A run is one request, so the text is at most
 * 1000 characters.
 */
export function VoiceLabForm({ state, onChange, onRun, running, voices }: VoiceLabFormProps) {
  const problem = formProblem(state);
  const mode = MODES.find((entry) => entry.value === state.mode);
  const instructionLabel = state.mode === "design" ? "Voice description" : "Instruction";

  function update(changes: Partial<VoiceLabFormState>) {
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
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Mode
          </Text>
          <SegmentedControl
            value={state.mode}
            onChange={(value) => update({ mode: value as VoiceMode })}
            data={MODES.map((entry) => ({ value: entry.value, label: entry.label }))}
          />
          <Text size="xs" c="dimmed">
            {mode?.help}
          </Text>
        </Stack>

        {needsVoice(state.mode) && (
          <Stack gap={4}>
            <Select
              label="Saved voice"
              placeholder={voices.length === 0 ? "No saved voices yet" : "Choose a voice"}
              data={voices.map((voice) => ({ value: String(voice.id), label: voice.name }))}
              value={state.voiceId}
              onChange={(voiceId) => update({ voiceId })}
              searchable
              nothingFoundMessage="No such voice"
            />
            {voices.length === 0 && (
              <Text size="xs" c="dimmed">
                Add a voice below: a clean recording and what it says, word for word.
              </Text>
            )}
          </Stack>
        )}

        <Textarea
          label="Text to speak"
          description={`${state.text.trim().length} of ${TEXT_MAX_CHARS} characters. Inline sounds: (laugh), (sigh), (clears throat) in English; [笑], [叹气] in Chinese.`}
          value={state.text}
          onChange={(event) => update({ text: event.currentTarget.value })}
          autosize
          minRows={4}
        />

        {takesInstruction(state.mode) && (
          <Textarea
            label={`${instructionLabel}${state.mode === "design" ? " (optional)" : ""}`}
            description={
              state.mode === "design"
                ? `For example: a warm, thoughtful young woman with a calm, reflective delivery. At most ${INSTRUCTION_MAX_CHARS} characters, in the language of the text.`
                : `For example: speak slowly with a restrained, serious tone. At most ${INSTRUCTION_MAX_CHARS} characters, in the language of the text.`
            }
            value={state.instruction}
            onChange={(event) => update({ instruction: event.currentTarget.value })}
            autosize
            minRows={2}
          />
        )}

        <Stack gap={4} align="flex-start">
          <TextInput
            label="Seed"
            description="Empty: random. The same inputs and seed give the same speech."
            value={state.seed}
            onChange={(event) => update({ seed: event.currentTarget.value })}
            w={320}
          />
          <NumberInput
            label="Guidance"
            description={`Empty: 4 with an instruction, 1 without. Above 0, at most ${CFG_SCALE_MAX}.`}
            value={state.cfgScale}
            onChange={(value) => update({ cfgScale: String(value) })}
            min={0}
            max={CFG_SCALE_MAX}
            step={1}
            decimalScale={2}
            allowNegative={false}
            clampBehavior="none"
            w={320}
          />
        </Stack>

        <Stack gap={6} align="flex-start">
          <Button type="submit" loading={running} disabled={problem !== null}>
            Make the speech
          </Button>
          {problem !== null && state.text.trim() !== "" && (
            <Alert color="yellow" p="xs">
              {problem}
            </Alert>
          )}
          <Text size="xs" c="dimmed">
            A GPU job of one to three minutes. It starts only when you press the button.
          </Text>
          <LicenseNotice />
        </Stack>
      </Stack>
    </form>
  );
}
