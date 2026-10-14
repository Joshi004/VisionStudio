import { useState } from "react";
import {
  Accordion,
  Alert,
  Button,
  Paper,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import { useCreateTake, type LibraryCharacter } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { LicenseNotice } from "../voiceLab/LicenseNotice";
import {
  DEFAULT_TAKE_FORM,
  FRAMING_LABELS,
  LIMITS,
  lookProblem,
  ORIENTATION_LABELS,
  OUTPUT_LABELS,
  takeCostNote,
  takeFormProblem,
  toTakeIn,
  VIDEO_MODEL_LABELS,
  visibleFields,
  type Framing,
  type Orientation,
  type Output,
  type TakeFormState,
  type VideoModel,
} from "./characterLabView";

function labelled<T extends string>(labels: Record<T, string>, values: readonly T[]) {
  return values.map((value) => ({ value, label: labels[value] }));
}

/**
 * The "try it" part: say what happens and, if the character has a voice, what it says, then
 * make an image, an audio or a video with one click. Only the fields that apply are shown.
 * One click starts the whole chain; the take appears in the gallery and shows each step.
 */
export function CreatePanel({ character }: { character: LibraryCharacter }) {
  const [form, setForm] = useState<TakeFormState>(DEFAULT_TAKE_FORM);
  const create = useCreateTake();
  const fields = visibleFields(form, character);
  const problem = takeFormProblem(form, character);
  const lookIssue = lookProblem(character);
  const typed = form.action.trim() !== "" || form.dialogue.trim() !== "";
  const makesSpeech =
    form.output === "audio" || (form.output === "video" && fields.dialogue && form.dialogue.trim() !== "");

  function update(changes: Partial<TakeFormState>) {
    create.reset();
    setForm((current) => ({ ...current, ...changes }));
  }

  const outputs: Output[] = fields.audio ? ["image", "video", "audio"] : ["image", "video"];

  return (
    <Paper withBorder p="md" radius="md">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (problem === null && !create.isPending) {
            create.mutate({ characterId: character.id, body: toTakeIn(form, character) });
          }
        }}
      >
        <Stack gap="md">
          <Text fw={600}>Create</Text>

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Make
            </Text>
            <SegmentedControl
              value={form.output}
              onChange={(value) => update({ output: value as Output })}
              data={labelled(OUTPUT_LABELS, outputs)}
            />
            {!fields.audio && (
              <Text size="xs" c="dimmed">
                This character is mute, so there is no audio and no dialogue. Give it a voice from
                Voice to change that.
              </Text>
            )}
          </Stack>

          {fields.action && (
            <Textarea
              label="What happens"
              description={`For example: sits on a cafe chair at sunrise, looking tired. ${form.action.length} of ${LIMITS.action} characters.`}
              value={form.action}
              onChange={(event) => update({ action: event.currentTarget.value })}
              autosize
              minRows={2}
            />
          )}

          {fields.dialogue && (
            <Textarea
              label={form.output === "audio" ? "What it says" : "Dialogue (optional)"}
              required={form.output === "audio"}
              description={`What the character says, in its own voice. ${form.dialogue.length} of ${LIMITS.speech} characters.`}
              value={form.dialogue}
              onChange={(event) => update({ dialogue: event.currentTarget.value })}
              autosize
              minRows={2}
            />
          )}

          {fields.videoModel && (
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Video model
              </Text>
              <SegmentedControl
                value={form.videoModel}
                onChange={(value) => update({ videoModel: value as VideoModel })}
                data={labelled(VIDEO_MODEL_LABELS, ["ltx-2.3", "ltx-2.5"] as const)}
              />
            </Stack>
          )}

          {fields.lipSync && (
            <Switch
              label="Lip sync"
              description="Redraws the mouth to match the speech. Takes several more minutes."
              checked={form.lipSync}
              onChange={(event) => update({ lipSync: event.currentTarget.checked })}
            />
          )}

          {fields.length && (
            <TextInput
              label="Length"
              description={`Seconds, from ${LIMITS.durationMin} to ${LIMITS.durationMax}. With speech, the clip is as long as the speech.`}
              inputMode="decimal"
              value={form.durationS}
              onChange={(event) => update({ durationS: event.currentTarget.value })}
              maw={240}
            />
          )}

          {fields.framing && (
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Framing
              </Text>
              <SegmentedControl
                value={form.framing}
                onChange={(value) => update({ framing: value as Framing })}
                data={labelled(FRAMING_LABELS, ["close_up", "medium", "wide"] as const)}
              />
              <Text size="xs" c="dimmed">
                Decides which of the character's pictures are used: the face for a close-up, the
                whole body for a wide shot.
              </Text>
            </Stack>
          )}

          {fields.orientation && (
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Orientation
              </Text>
              <SegmentedControl
                value={form.orientation}
                onChange={(value) => update({ orientation: value as Orientation })}
                data={labelled(ORIENTATION_LABELS, ["portrait", "landscape"] as const)}
              />
            </Stack>
          )}

          {(fields.seed || fields.negativePrompt) && (
            <Accordion variant="contained">
              <Accordion.Item value="advanced">
                <Accordion.Control>Advanced</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="sm">
                    {fields.seed && (
                      <TextInput
                        label="Seed"
                        description="Empty: random. The same inputs and seed give the same picture."
                        inputMode="numeric"
                        value={form.seed}
                        onChange={(event) => update({ seed: event.currentTarget.value })}
                        maw={240}
                      />
                    )}
                    {fields.negativePrompt && (
                      <Textarea
                        label="Negative prompt (LTX-2.3 only)"
                        description={`What to avoid in the clip. ${form.negativePrompt.length} of ${LIMITS.negativePrompt} characters.`}
                        value={form.negativePrompt}
                        onChange={(event) => update({ negativePrompt: event.currentTarget.value })}
                        autosize
                        minRows={2}
                      />
                    )}
                    <Text size="xs" c="dimmed">
                      The prompts the language model writes appear on the take once they are ready,
                      and can be edited there.
                    </Text>
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
          )}

          <Stack gap={6} align="flex-start">
            <Button type="submit" loading={create.isPending} disabled={problem !== null}>
              Create
            </Button>
            {problem !== null && (lookIssue !== null || typed) && (
              <Alert color="yellow" p="xs">
                {problem}
              </Alert>
            )}
            {create.isError && (
              <Alert color="red" p="xs" title="Nothing was started">
                {describeError(create.error)}
              </Alert>
            )}
            {create.isSuccess && (
              <Alert color="green" p="xs">
                Started. Follow it in the gallery below: this page updates by itself.
              </Alert>
            )}
            <Text size="xs" c="dimmed">
              {takeCostNote(form, character)} It starts only when you press the button.
            </Text>
            {makesSpeech && <LicenseNotice />}
          </Stack>
        </Stack>
      </form>
    </Paper>
  );
}
