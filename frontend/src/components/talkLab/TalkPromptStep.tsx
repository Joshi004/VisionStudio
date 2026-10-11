import { useState, type Dispatch, type SetStateAction } from "react";
import { Alert, Button, Group, Paper, Stack, Text, Textarea, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJob } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import { useCreateTalkPromptDraft } from "../../api/talkLab";
import { useNow } from "../../hooks/useNow";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import {
  VIDEO_PROMPT_MAX_CHARS,
  VOICE_INSTRUCTION_MAX_CHARS,
  wantsVoiceInstruction,
  type TalkFormState,
} from "./talkLabView";

type TalkPromptStepProps = {
  state: TalkFormState;
  onChange: Dispatch<SetStateAction<TalkFormState>>;
};

type WrittenPrompts = { voice: string; video: string; warnings: string[] };

/** What the finished job says (`job.output` is stored JSON, so it is read defensively). */
function readOutput(output: unknown): WrittenPrompts | null {
  if (typeof output !== "object" || output === null) {
    return null;
  }
  const record = output as Record<string, unknown>;
  if (typeof record.video_prompt !== "string") {
    return null;
  }
  const warnings = Array.isArray(record.warnings)
    ? record.warnings.filter((item): item is string => typeof item === "string")
    : [];
  return {
    voice: typeof record.voice_instruction === "string" ? record.voice_instruction : "",
    video: record.video_prompt,
    warnings,
  };
}

function Quoted({ label, text }: { label: string; text: string }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text
        size="sm"
        p="xs"
        style={{
          border: "1px solid var(--mantine-color-gray-3)",
          borderRadius: 6,
          background: "white",
          whiteSpace: "pre-wrap",
        }}
      >
        {text}
      </Text>
    </Stack>
  );
}

/**
 * Step 2: the two prompts of a take. The voice instruction steers the speech model, and the
 * video prompt tells the video model what to show. Write them by hand, or press the button and a
 * language model writes both from the dialogue and the character. That is a paid call, made only
 * when the button is pressed, and what it writes is not put in the form until you choose to use
 * it: nothing you typed is overwritten.
 */
export function TalkPromptStep({ state, onChange }: TalkPromptStepProps) {
  const [jobId, setJobId] = useState<number | null>(null);
  const draft = useCreateTalkPromptDraft();
  const job = useJob(jobId);

  const current = job.data;
  const active = isJobActive(current) || draft.isPending;
  const now = useNow(active, job.dataUpdatedAt);
  const result = current?.status === "succeeded" ? readOutput(current.output) : null;
  const wantsVoice = wantsVoiceInstruction(state);
  const canWrite = state.dialogue.trim() !== "" && !active;

  function write() {
    draft.mutate(
      {
        dialogue: state.dialogue,
        character_id: state.characterId === null ? null : Number(state.characterId),
        character_note: state.characterNote.trim() === "" ? null : state.characterNote,
        image: state.image === null ? null : { source: state.image.source, id: state.image.id },
        delivery_note: state.deliveryNote.trim() === "" ? null : state.deliveryNote,
        voice_mode: state.speech === "new" ? state.voiceMode : null,
      },
      { onSuccess: (created) => setJobId(created.id) },
    );
  }

  function applyResult(written: WrittenPrompts) {
    onChange((form) => ({
      ...form,
      videoPrompt: written.video,
      voiceInstruction:
        wantsVoiceInstruction(form) && written.voice !== "" ? written.voice : form.voiceInstruction,
    }));
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Stack gap={2}>
          <Title order={5}>2. Prompts</Title>
          <Text size="xs" c="dimmed">
            The voice instruction steers the speech model. The video prompt describes what the
            video model shows: the speaker and the act of speaking, never the words (the speech is
            given to it as sound). Write them, or let a language model write both. Left empty, the
            run-all button writes whatever is missing first.
          </Text>
        </Stack>

        <Group gap="sm">
          <Button variant="default" onClick={write} disabled={!canWrite} loading={draft.isPending}>
            Write both with AI
          </Button>
          {current && (
            <Group gap="xs">
              <JobStatusBadge job={current} />
              <Text size="sm" c="dimmed">
                {elapsedText(current, now)}
              </Text>
            </Group>
          )}
        </Group>
        {state.dialogue.trim() === "" && (
          <Text size="xs" c="dimmed">
            Write the dialogue in step 1 first.
          </Text>
        )}

        {draft.isError && (
          <Alert color="red" title="The prompts were not started">
            {describeError(draft.error)}
          </Alert>
        )}
        {current?.status === "failed" && current.error && (
          <Alert color="red" title="The prompts could not be written">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {current.error}
            </Text>
          </Alert>
        )}

        {result && (
          <Paper withBorder p="sm" radius="md" bg="var(--mantine-color-gray-0)">
            <Stack gap="xs">
              {result.voice !== "" && <Quoted label="Voice instruction" text={result.voice} />}
              <Quoted label="Video prompt" text={result.video} />
              {result.warnings.map((warning) => (
                <Text key={warning} size="xs" c="orange.8">
                  {warning}
                </Text>
              ))}
              <Group gap="sm">
                <Button size="compact-sm" onClick={() => applyResult(result)}>
                  Use these prompts
                </Button>
                <Text size="xs" c="dimmed">
                  They replace the prompts below. Pressing the button again writes new ones.
                </Text>
              </Group>
            </Stack>
          </Paper>
        )}

        {wantsVoice && (
          <Textarea
            label={state.voiceMode === "design" ? "Voice description" : "Delivery instruction"}
            description={
              state.voiceMode === "design"
                ? "Who the voice sounds like, and how the line is said. Left empty, it is written for you."
                : "How the saved voice says it: tone, emotion, pace. Direction needs one; left empty, it is written for you."
            }
            value={state.voiceInstruction}
            onChange={(event) => {
              const voiceInstruction = event.currentTarget.value;
              onChange((form) => ({ ...form, voiceInstruction }));
            }}
            maxLength={VOICE_INSTRUCTION_MAX_CHARS}
            autosize
            minRows={2}
          />
        )}
        <Textarea
          label="Video prompt"
          description={`What the video model shows. Left empty, it is written for you. ${state.videoPrompt.trim().length} of ${VIDEO_PROMPT_MAX_CHARS.toLocaleString()} characters.`}
          placeholder="A lighthouse keeper in his sixties, in a navy wool cap, speaks directly to the camera. His lips move naturally with each word. The camera holds steady."
          value={state.videoPrompt}
          onChange={(event) => {
            const videoPrompt = event.currentTarget.value;
            onChange((form) => ({ ...form, videoPrompt }));
          }}
          maxLength={VIDEO_PROMPT_MAX_CHARS}
          autosize
          minRows={3}
        />
      </Stack>
    </Paper>
  );
}
