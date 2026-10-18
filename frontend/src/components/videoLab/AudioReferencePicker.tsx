import { Alert, Group, Loader, Select, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useVoiceLabRuns, useVoices } from "../../api/voiceLab";
import { type AudioChoice } from "./videoLabView";

type AudioReferencePickerProps = {
  value: AudioChoice | null;
  onChange: (value: AudioChoice | null) => void;
  /** Replaces the heading ("Audio reference"), for a form where the audio has another role. */
  title?: string;
  /** Replaces the note under the picker. */
  hint?: string;
};

/** One thing that can be the audio reference, with the file to preview. */
type Candidate = { key: string; choice: AudioChoice; url: string | null };

const SPEECH_LABEL_CHARS = 40;

function keyOf(choice: Pick<AudioChoice, "source" | "id">): string {
  return `${choice.source}:${choice.id}`;
}

/** Any recording with a length can be tried: the GPU server decides what it does with it. */
function fits(durationS: number): boolean {
  return durationS > 0;
}

function optionLabel(candidate: Candidate): string {
  return `${candidate.choice.label} (${candidate.choice.durationS.toFixed(2)} s)`;
}

/**
 * The audio reference of a MiniMax H3 reference clip (`<Audio 1>`): a saved voice's recording or
 * a finished Voice lab speech (the server documents 2 to 15 seconds). The model reads it for the voice (timbre
 * and delivery) and makes its own soundtrack, so the clip's sound is not this recording.
 */
export function AudioReferencePicker({ value, onChange, title, hint }: AudioReferencePickerProps) {
  const voices = useVoices();
  const runs = useVoiceLabRuns();

  const saved: Candidate[] = (voices.data ?? []).map((voice) => ({
    key: keyOf({ source: "voice", id: voice.id }),
    choice: {
      source: "voice",
      id: voice.id,
      label: `voice: ${voice.name}`,
      durationS: voice.duration_s,
    },
    url: voice.url,
  }));
  const speeches: Candidate[] = (runs.data?.pages.flat() ?? [])
    .filter((run) => run.url !== null && run.duration_s !== null)
    .map((run) => {
      const text = run.text.length > SPEECH_LABEL_CHARS ? `${run.text.slice(0, SPEECH_LABEL_CHARS)}…` : run.text;
      return {
        key: keyOf({ source: "voice_run", id: run.id }),
        choice: {
          source: "voice_run" as const,
          id: run.id,
          label: `speech ${run.id}: ${text}`,
          durationS: run.duration_s ?? 0,
        },
        url: run.url,
      };
    });

  const all = [...saved, ...speeches];
  const current = value === null ? undefined : all.find((item) => item.key === keyOf(value));
  const groups = [
    {
      group: "Saved voices",
      items: saved.map((item) => ({
        value: item.key,
        label: optionLabel(item),
        disabled: !fits(item.choice.durationS),
      })),
    },
    {
      group: "Voice lab speeches",
      items: speeches.map((item) => ({
        value: item.key,
        label: optionLabel(item),
        disabled: !fits(item.choice.durationS),
      })),
    },
  ].filter((group) => group.items.length > 0);
  // A run loaded into the form may name a recording that is not in these lists (yet): keep it
  // chosen, so the form does not lose it.
  if (value !== null && current === undefined) {
    groups.push({
      group: "Chosen",
      items: [{ value: keyOf(value), label: value.label, disabled: false }],
    });
  }

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        {title ?? "Audio reference"}
      </Text>
      <Select
        aria-label={title ?? "Audio reference"}
        placeholder={
          voices.isLoading || runs.isLoading ? "Loading…" : "Choose a saved voice or a speech"
        }
        data={groups}
        value={value === null ? null : keyOf(value)}
        onChange={(key) => {
          const picked = all.find((item) => item.key === key);
          onChange(picked === undefined ? null : picked.choice);
        }}
        searchable
        clearable
        nothingFoundMessage="No voice or speech."
        maw={520}
      />
      {(voices.isLoading || runs.isLoading) && <Loader size="xs" />}
      {(voices.isError || runs.isError) && (
        <Alert color="red" p="xs" title="Could not load the voices">
          {describeError(voices.error ?? runs.error)}
        </Alert>
      )}
      {current !== undefined && current.url !== null && (
        <Group gap="sm" align="center">
          <audio src={current.url} controls preload="none" style={{ maxWidth: 360 }} />
        </Group>
      )}
      <Text size="xs" c="dimmed">
        {hint ?? (
          <>
            Any length can be tried (the server documents 2 to 15 seconds). MiniMax H3 follows its
            voice and delivery but makes its own sound: for the exact recording, use the Characters
            tab.
          </>
        )}
      </Text>
    </Stack>
  );
}
