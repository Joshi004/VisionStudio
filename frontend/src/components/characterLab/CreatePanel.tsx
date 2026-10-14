import type { Dispatch, SetStateAction } from "react";
import {
  Accordion,
  Alert,
  Button,
  Checkbox,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import { useCreateTake, type AudioMarker, type LibraryCharacter } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { FirstFramePicker } from "../videoLab/FirstFramePicker";
import { AudioReferencePicker } from "../videoLab/AudioReferencePicker";
import { H3_AUDIO_MAX_S, H3_AUDIO_MIN_S, H3_STEPS_MAX, H3_STEPS_MIN } from "../videoLab/videoLabView";
import { LicenseNotice } from "../voiceLab/LicenseNotice";
import {
  AUDIO_MARKER_HINTS,
  AUDIO_MARKERS,
  CREATE_PANEL_ID,
  FRAMING_LABELS,
  LIMITS,
  lengthLimits,
  lookProblem,
  matchesAudio,
  ORIENTATION_LABELS,
  OUTPUT_LABELS,
  takeCostNote,
  takeFormProblem,
  toTakeIn,
  VIDEO_MODEL_LABELS,
  VIDEO_MODELS,
  visibleFields,
  type Framing,
  type LastFrameMode,
  type Orientation,
  type Output,
  type SourceMode,
  type TakeFormState,
  type VideoModel,
} from "./characterLabView";

function labelled<T extends string>(labels: Record<T, string>, values: readonly T[]) {
  return values.map((value) => ({ value, label: labels[value] }));
}

const FIRST_FRAME_MODES: { value: SourceMode; label: string }[] = [
  { value: "make", label: "Make it" },
  { value: "pick", label: "Use a picture" },
];

const LAST_FRAME_MODES: { value: LastFrameMode; label: string }[] = [
  { value: "none", label: "None" },
  { value: "make", label: "Make it from the first frame" },
  { value: "pick", label: "Use a picture" },
];

const SPEECH_MODES: { value: SourceMode; label: string }[] = [
  { value: "make", label: "Make it in the character's voice" },
  { value: "pick", label: "Use an existing recording" },
];

type CreatePanelProps = {
  character: LibraryCharacter;
  /** The form lives in the page, so a take in the gallery can fill it ("New take from this"). */
  form: TakeFormState;
  onChange: Dispatch<SetStateAction<TakeFormState>>;
};

/**
 * The "try it" part: say what happens and, if the character has a voice, what it says, then
 * make an image, an audio or a video with one click. Only the fields that apply are shown.
 * One click starts the whole chain; the take appears in the gallery and shows each step.
 *
 * With MiniMax H3 the frames and the speech can be picked instead of made, so one request can
 * be tried again (another marker, another seed) without paying for them twice.
 */
export function CreatePanel({ character, form, onChange }: CreatePanelProps) {
  const create = useCreateTake();
  const fields = visibleFields(form, character);
  const problem = takeFormProblem(form, character);
  const lookIssue = lookProblem(character);
  const typed = form.action.trim() !== "" || form.dialogue.trim() !== "";
  const makesSpeech =
    form.output === "audio" ||
    (form.output === "video" &&
      fields.dialogue &&
      form.dialogue.trim() !== "" &&
      !(fields.h3Speech && form.audioMode === "pick"));
  const lengths = lengthLimits(form);
  const copiesSpeech = form.audioMarker === "fully_copy" || form.audioMarker === "partially_copy";

  function update(changes: Partial<TakeFormState>) {
    create.reset();
    onChange((current) => ({ ...current, ...changes }));
  }

  const outputs: Output[] = fields.audio ? ["image", "video", "audio"] : ["image", "video"];

  return (
    <Paper withBorder p="md" radius="md" id={CREATE_PANEL_ID}>
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
              description={
                `What the character says, in its own voice. ${form.dialogue.length} of ${LIMITS.speech} characters.` +
                (fields.h3Speech
                  ? ` MiniMax H3 needs the speech to last ${H3_AUDIO_MIN_S} to ${H3_AUDIO_MAX_S} seconds.`
                  : "") +
                (fields.h3Speech && form.audioMode === "pick" && copiesSpeech
                  ? " With a copy marker, write exactly what the recording says."
                  : "")
              }
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
                data={labelled(VIDEO_MODEL_LABELS, VIDEO_MODELS)}
              />
            </Stack>
          )}

          {fields.h3 && (
            <Paper withBorder p="sm" radius="md" bg="var(--mantine-color-gray-0)">
              <Stack gap="md">
                <Text size="sm" fw={600}>
                  MiniMax H3
                </Text>
                <Text size="xs" c="dimmed">
                  {fields.h3Speech
                    ? `With dialogue, H3 hears the speech as a reference and makes the clip's sound itself. Its reference mode has no first-frame field, so the first frame is given as <Picture 1>${form.lastFrameMode === "none" ? "" : " and the last frame as <Picture 2>"}: the clip starts near the picture, not exactly on it.`
                    : "Without dialogue, H3 starts the clip exactly on the first frame (and ends on the last frame, if there is one) and makes the sound itself."}
                </Text>

                <Stack gap="xs">
                  <Text size="sm" fw={500}>
                    First frame
                  </Text>
                  <SegmentedControl
                    value={form.firstFrameMode}
                    onChange={(value) => update({ firstFrameMode: value as SourceMode })}
                    data={FIRST_FRAME_MODES}
                  />
                  {form.firstFrameMode === "pick" && (
                    <FirstFramePicker
                      value={form.firstFrame}
                      onChange={(firstFrame) => update({ firstFrame })}
                      title="First frame picture"
                      emptyText="No picture chosen yet."
                      hint="The clip starts from this picture. The language model is told the prompt it was made from, when it has one."
                    />
                  )}
                </Stack>

                <Stack gap="xs">
                  <Text size="sm" fw={500}>
                    Last frame
                  </Text>
                  <SegmentedControl
                    value={form.lastFrameMode}
                    onChange={(value) => update({ lastFrameMode: value as LastFrameMode })}
                    data={LAST_FRAME_MODES}
                  />
                  {form.lastFrameMode === "make" && (
                    <Text size="xs" c="dimmed">
                      The language model writes an edit instruction, and the first frame is edited
                      into the last frame: the same shot when the action has ended. One more picture
                      to pay for.
                    </Text>
                  )}
                  {form.lastFrameMode === "pick" && (
                    <FirstFramePicker
                      role="last"
                      value={form.lastFrame}
                      onChange={(lastFrame) => update({ lastFrame })}
                      title="Last frame picture"
                    />
                  )}
                </Stack>

                {fields.h3Speech && (
                  <>
                    <Stack gap="xs">
                      <Text size="sm" fw={500}>
                        Speech
                      </Text>
                      <SegmentedControl
                        value={form.audioMode}
                        onChange={(value) => update({ audioMode: value as SourceMode })}
                        data={SPEECH_MODES}
                      />
                      {form.audioMode === "pick" && (
                        <AudioReferencePicker
                          title="Recording to use"
                          hint={`${H3_AUDIO_MIN_S} to ${H3_AUDIO_MAX_S} seconds: a saved voice's recording, or a speech from the Voice lab (including the one a take of this character made).`}
                          value={form.audio}
                          onChange={(audio) => update({ audio })}
                        />
                      )}
                    </Stack>

                    <Select
                      label="How the speech is used"
                      description={AUDIO_MARKER_HINTS[form.audioMarker]}
                      data={AUDIO_MARKERS.map((marker) => ({ value: marker, label: marker }))}
                      value={form.audioMarker}
                      onChange={(marker) => marker && update({ audioMarker: marker as AudioMarker })}
                      allowDeselect={false}
                      maw={520}
                    />

                    <Checkbox
                      label="Make the clip as long as the speech"
                      description={
                        form.audioMarker === "fully_copy"
                          ? "fully_copy needs it: the speech is the whole soundtrack."
                          : `Otherwise the clip lasts the length below, from ${lengths.min} to ${lengths.max} seconds.`
                      }
                      checked={matchesAudio(form)}
                      disabled={form.audioMarker === "fully_copy"}
                      onChange={(event) => update({ matchAudio: event.currentTarget.checked })}
                    />
                  </>
                )}
              </Stack>
            </Paper>
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
              description={
                fields.h3
                  ? `Seconds, from ${lengths.min} to ${lengths.max}. MiniMax H3 makes at least 5.17 seconds.`
                  : `Seconds, from ${lengths.min} to ${lengths.max}. With speech, the clip is as long as the speech.`
              }
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

          {(fields.seed || fields.negativePrompt || fields.h3) && (
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
                    {fields.h3 && (
                      <TextInput
                        label="Steps (MiniMax H3)"
                        description={`From ${H3_STEPS_MIN} to ${H3_STEPS_MAX}. Empty: the pipeline's own number (50). More steps take longer.`}
                        inputMode="numeric"
                        value={form.steps}
                        onChange={(event) => update({ steps: event.currentTarget.value })}
                        maw={240}
                      />
                    )}
                    {fields.h3Speech && (
                      <Switch
                        label="Also send the character's pictures as references"
                        description="The pictures the first frame is made from follow the frames as extra references. Off by default: they may compete with the first frame."
                        checked={form.identityRefs}
                        onChange={(event) => update({ identityRefs: event.currentTarget.checked })}
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
