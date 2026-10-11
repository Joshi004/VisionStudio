import type { Dispatch, SetStateAction } from "react";
import {
  Alert,
  Button,
  Group,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";

import { useCharacters } from "../../api/characters";
import { useVoiceLabRuns, useVoices } from "../../api/voiceLab";
import { FirstFramePicker } from "../videoLab/FirstFramePicker";
import { LicenseNotice } from "../voiceLab/LicenseNotice";
import { MODES, needsVoice, type VoiceMode } from "../voiceLab/voiceLabView";
import {
  CHARACTER_NOTE_MAX_CHARS,
  CLIP_MAX_S,
  DELIVERY_NOTE_MAX_CHARS,
  DIALOGUE_MAX_CHARS,
  NEGATIVE_PROMPT_MAX_CHARS,
  estimateSpeechSeconds,
  formProblem,
  withCharacter,
  type TalkFormState,
  type TalkRun,
} from "./talkLabView";
import { TalkPromptStep } from "./TalkPromptStep";

type TalkLabFormProps = {
  state: TalkFormState;
  onChange: Dispatch<SetStateAction<TalkFormState>>;
  /** Starts a take: the whole chain, or only the speech, or only the clip. */
  onRun: (run: TalkRun) => void;
  /** The click that is being sent now, or null. */
  starting: TalkRun | null;
};

function snippet(text: string, length: number): string {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length <= length ? line : `${line.slice(0, length - 1)}…`;
}

/** A button that starts `run`, and says why it cannot when it cannot. */
function RunButton({
  label,
  run,
  state,
  onRun,
  starting,
  primary = false,
}: {
  label: string;
  run: TalkRun;
  state: TalkFormState;
  onRun: (run: TalkRun) => void;
  starting: TalkRun | null;
  primary?: boolean;
}) {
  const problem = formProblem(state, run);
  return (
    <Stack gap={6} align="flex-start">
      <Button
        variant={primary ? "filled" : "default"}
        loading={starting === run}
        disabled={problem !== null || starting !== null}
        onClick={() => onRun(run)}
      >
        {label}
      </Button>
      {problem !== null && state.dialogue.trim() !== "" && (
        <Alert color="yellow" p="xs">
          {problem}
        </Alert>
      )}
    </Stack>
  );
}

/**
 * The Talking character form, in the order a take is made: the character and the line, the two
 * prompts, the speech and the video. Every step has a button of its own, so each can be tried
 * and repeated alone (the same speech can have many clips made for it), and "Run all" makes the
 * whole take and keeps going when you leave the page. A step is a paid call that starts only
 * when you press its button.
 */
export function TalkLabForm({ state, onChange, onRun, starting }: TalkLabFormProps) {
  const characters = useCharacters();
  const voices = useVoices();
  const speeches = useVoiceLabRuns();

  const finished = (speeches.data?.pages.flat() ?? []).filter((run) => run.url !== null);
  const chosenSpeech = finished.find((run) => String(run.id) === state.reuseRunId) ?? null;
  const speechOptions = finished.map((run) => ({
    value: String(run.id),
    label: `#${run.id} · ${snippet(run.text, 40)} · ${(run.duration_s ?? 0).toFixed(1)} s`,
  }));
  if (state.reuseRunId !== null && chosenSpeech === null) {
    // A speech that is not in the newest page, or is still being made.
    speechOptions.unshift({ value: state.reuseRunId, label: `Speech #${state.reuseRunId}` });
  }

  const estimate = estimateSpeechSeconds(state.dialogue);
  const tooLong = estimate > CLIP_MAX_S * 0.9;
  const mode = MODES.find((item) => item.value === state.voiceMode);

  function update(changes: Partial<TalkFormState>) {
    onChange((form) => ({ ...form, ...changes }));
  }

  return (
    <Stack gap="md">
      {/* --- 1. The character and the line ------------------------------------------------ */}
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Title order={5}>1. Character and line</Title>
          <Select
            label="Cast character (optional)"
            description="Fills in the picture and the voice, and tells the AI who the character is. Save characters from the library."
            placeholder="None: use a picture of your own"
            data={(characters.data ?? []).map((character) => ({
              value: String(character.id),
              label: character.name,
            }))}
            value={state.characterId}
            onChange={(value) => {
              const character = characters.data?.find((item) => String(item.id) === value);
              if (character !== undefined) {
                onChange((form) => withCharacter(form, character));
              } else {
                update({ characterId: null });
              }
            }}
            clearable
            searchable
            nothingFoundMessage="No characters"
          />
          <FirstFramePicker
            value={state.image}
            onChange={(image) =>
              onChange((form) => ({
                ...form,
                image,
                // Another picture is not the cast character's picture any more.
                characterId:
                  image !== null &&
                  form.image !== null &&
                  image.source === form.image.source &&
                  image.id === form.image.id
                    ? form.characterId
                    : null,
              }))
            }
            title="Character picture"
            emptyText="No picture yet. The video starts from this picture, so the character looks like it."
            hint="The clip starts on this picture and the character speaks from it. It is cut to the clip's shape (centred), so use a picture that shows the face."
          />
          <Textarea
            label="Dialogue"
            description={
              state.dialogue.trim() === ""
                ? `The line the character says, at most ${DIALOGUE_MAX_CHARS.toLocaleString()} characters.`
                : `${state.dialogue.trim().length} of ${DIALOGUE_MAX_CHARS.toLocaleString()} characters · about ${estimate.toFixed(0)} s of speech (a guess: the clip is as long as the speech that is made).`
            }
            placeholder="You shouldn't be up here after dark. The rocks don't forgive mistakes."
            value={state.dialogue}
            onChange={(event) => update({ dialogue: event.currentTarget.value })}
            maxLength={DIALOGUE_MAX_CHARS}
            autosize
            minRows={2}
          />
          {tooLong && (
            <Alert color="orange" p="xs">
              A clip is at most {CLIP_MAX_S} seconds, and this line may be longer. A speech that
              is longer is refused when the video starts, after the speech has been paid for:
              shorten the line.
            </Alert>
          )}
          <Textarea
            label="What the character is like (optional)"
            description={`Face, hair, clothes, place. The AI that writes the prompts cannot see the picture. Left empty, the cast character's description is used. ${state.characterNote.trim().length} of ${CHARACTER_NOTE_MAX_CHARS.toLocaleString()} characters.`}
            placeholder="A lighthouse keeper in his sixties with a grey beard and a navy wool cap."
            value={state.characterNote}
            onChange={(event) => update({ characterNote: event.currentTarget.value })}
            maxLength={CHARACTER_NOTE_MAX_CHARS}
            autosize
            minRows={2}
          />
          <Textarea
            label="How it is said (optional)"
            description={`Tone and emotion, for the voice and the face. ${state.deliveryNote.trim().length} of ${DELIVERY_NOTE_MAX_CHARS} characters.`}
            placeholder="Gruff but quietly worried, speaking slowly."
            value={state.deliveryNote}
            onChange={(event) => update({ deliveryNote: event.currentTarget.value })}
            maxLength={DELIVERY_NOTE_MAX_CHARS}
            autosize
            minRows={1}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Shape of the clip
            </Text>
            <SegmentedControl
              value={state.orientation}
              onChange={(value) => update({ orientation: value === "landscape" ? "landscape" : "portrait" })}
              data={[
                { value: "portrait", label: "Portrait (1088 x 1920)" },
                { value: "landscape", label: "Landscape (1920 x 1088)" },
              ]}
            />
          </Stack>
        </Stack>
      </Paper>

      {/* --- 2. The prompts ---------------------------------------------------------------- */}
      <TalkPromptStep state={state} onChange={onChange} />

      {/* --- 3. The speech ----------------------------------------------------------------- */}
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Title order={5}>3. Speech</Title>
          <SegmentedControl
            value={state.speech}
            onChange={(value) => {
              if (value === "reuse") {
                // The newest finished speech is the one the last take made, so it is the default.
                const newest = finished[0];
                onChange((form) => ({
                  ...form,
                  speech: "reuse",
                  reuseRunId:
                    form.reuseRunId ?? (newest !== undefined ? String(newest.id) : null),
                }));
              } else {
                update({ speech: "new" });
              }
            }}
            data={[
              { value: "new", label: "New speech" },
              { value: "reuse", label: "Reuse a speech" },
            ]}
          />

          {state.speech === "new" ? (
            <>
              <Select
                label="How the voice is made"
                description={mode?.help}
                data={MODES.map((item) => ({ value: item.value, label: item.label }))}
                value={state.voiceMode}
                onChange={(value) => {
                  const next = MODES.find((item) => item.value === value);
                  if (next !== undefined) {
                    update({ voiceMode: next.value as VoiceMode });
                  }
                }}
                allowDeselect={false}
              />
              {needsVoice(state.voiceMode) && (
                <Select
                  label="Saved voice"
                  description="A clean recording and its exact words. Save one from a speech in the Voice tab."
                  placeholder="Choose a voice"
                  data={(voices.data ?? []).map((voice) => ({
                    value: String(voice.id),
                    label: voice.name,
                  }))}
                  value={state.voiceId}
                  onChange={(voiceId) => update({ voiceId })}
                  searchable
                  nothingFoundMessage="No saved voices"
                />
              )}
              <Text size="xs" c="dimmed">
                A speech is a paid GPU job of one to three minutes. It is also kept in the Voice tab,
                where it can be saved as a voice.
              </Text>
              <RunButton
                label="Make speech"
                run="voice"
                state={state}
                onRun={onRun}
                starting={starting}
              />
            </>
          ) : (
            <>
              <Select
                label="Speech to reuse"
                description="A finished speech from the Voice tab or an earlier take. Reusing it makes a new clip of the same recording, without paying for the speech again."
                placeholder={finished.length === 0 ? "No finished speeches yet" : "Choose a speech"}
                data={speechOptions}
                value={state.reuseRunId}
                onChange={(reuseRunId) => update({ reuseRunId })}
                searchable
              />
              {chosenSpeech?.url != null && (
                <audio
                  key={chosenSpeech.id}
                  src={chosenSpeech.url}
                  controls
                  preload="metadata"
                  style={{ width: "100%" }}
                />
              )}
            </>
          )}
          <LicenseNotice />
        </Stack>
      </Paper>

      {/* --- 4. The video ------------------------------------------------------------------ */}
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Title order={5}>4. Video</Title>
          <Text size="xs" c="dimmed">
            LTX-2.3 makes the character speak the recording, with the lips following it, and the
            recording is the clip's sound.{" "}
            {chosenSpeech !== null && chosenSpeech.duration_s !== null
              ? `The clip will be as long as the chosen speech: ${chosenSpeech.duration_s.toFixed(1)} seconds.`
              : "The clip is as long as the speech, up to " + `${CLIP_MAX_S} seconds.`}
          </Text>
          <Group align="flex-start" grow>
            <TextInput
              label="Seed"
              description="Empty: a random seed. The same seed and inputs give the same clip."
              value={state.videoSeed}
              onChange={(event) => update({ videoSeed: event.currentTarget.value })}
              inputMode="numeric"
            />
          </Group>
          <Textarea
            label="Negative prompt (optional)"
            description={`What to steer away from. Empty: the pipeline's own default. ${state.negativePrompt.trim().length} of ${NEGATIVE_PROMPT_MAX_CHARS.toLocaleString()} characters.`}
            value={state.negativePrompt}
            onChange={(event) => update({ negativePrompt: event.currentTarget.value })}
            maxLength={NEGATIVE_PROMPT_MAX_CHARS}
            autosize
            minRows={1}
          />
          <Text size="xs" c="dimmed">
            A clip is a paid GPU job of 5 to 10 minutes, and it uses the same GPU slots as scene
            clips. It is also kept in the Video tab.
          </Text>
          <RunButton
            label="Make video"
            run="video"
            state={state}
            onRun={onRun}
            starting={starting}
          />
        </Stack>
      </Paper>

      {/* --- Run everything ---------------------------------------------------------------- */}
      <Paper withBorder p="md" radius="md">
        <Stack gap="xs">
          <RunButton
            label="Run all"
            run="all"
            state={state}
            onRun={onRun}
            starting={starting}
            primary
          />
          <Text size="xs" c="dimmed">
            Makes the whole take: the prompts that are missing (a call to the language model), then
            the speech (unless you reuse one), then the video. Each step starts by itself when the
            one before it has finished, even if you leave this page. Nothing starts until you press
            a button.
          </Text>
        </Stack>
      </Paper>
    </Stack>
  );
}
