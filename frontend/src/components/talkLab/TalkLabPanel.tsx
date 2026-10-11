import { useState, type Dispatch, type SetStateAction } from "react";
import { Alert, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useCreateTalkTake, type TalkTake } from "../../api/talkLab";
import { TalkLabForm } from "./TalkLabForm";
import { TalkTakeList } from "./TalkTakeList";
import { formProblem, stateFromTake, toRequest, type TalkFormState, type TalkRun } from "./talkLabView";

type TalkLabPanelProps = {
  /** The form lives in the Lab page, so the library can fill it from any tab. */
  form: TalkFormState;
  onFormChange: Dispatch<SetStateAction<TalkFormState>>;
};

const STARTED_TEXT: Record<TalkRun, string> = {
  all: "The take is running. Each step starts by itself when the one before has finished, so you can leave this page.",
  voice: "The speech is waiting for a free GPU slot. When it is done, use Next on the take to go on.",
  video: "The clip is waiting for a free GPU slot and takes 5 to 10 minutes.",
};

/**
 * The Talking character tab: a character picture says one line of dialogue, lip-synced. The line
 * is spoken by the speech model (Breeze TTS 2), and the video model (LTX-2.3 audio-to-video)
 * makes the character speak that recording. A language model can write the prompts for both. It
 * belongs to no project and changes none. Every step is a paid call and starts only from a
 * click; the speech and the clip also appear in the Voice and Video tabs.
 */
export function TalkLabPanel({ form, onFormChange }: TalkLabPanelProps) {
  const create = useCreateTalkTake();
  const [starting, setStarting] = useState<TalkRun | null>(null);
  const [rerolling, setRerolling] = useState<number | null>(null);
  const [started, setStarted] = useState<TalkRun | null>(null);
  const [rerollProblem, setRerollProblem] = useState<string | null>(null);

  function run(kind: TalkRun) {
    setStarting(kind);
    setStarted(null);
    setRerollProblem(null);
    create.mutate(toRequest(form, kind), {
      onSuccess: () => setStarted(kind),
      onSettled: () => setStarting(null),
    });
  }

  function reroll(take: TalkTake) {
    const state = stateFromTake(take, true);
    const problem = formProblem(state, "video");
    setStarted(null);
    if (problem !== null) {
      setRerollProblem(problem);
      return;
    }
    setRerollProblem(null);
    setRerolling(take.id);
    create.mutate(toRequest(state, "video"), {
      onSuccess: () => setStarted("video"),
      onSettled: () => setRerolling(null),
    });
  }

  function loadIntoForm(next: TalkFormState) {
    onFormChange(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <Stack gap="lg" maw={1100}>
      <Text size="sm" c="dimmed">
        Make a character say a line. Choose a picture and write the dialogue. The speech model
        reads the line in a voice you describe, a saved voice or a directed one (or you reuse an
        earlier speech), and the video model makes the character speak that recording with the
        lips following it. A language model can write the prompts for both. Each step is a paid
        call that starts only when you press its button, and each can be repeated alone.
      </Text>

      <TalkLabForm state={form} onChange={onFormChange} onRun={run} starting={starting} />

      {create.isError && (
        <Alert color="red" title="The take was not started">
          {describeError(create.error)}
        </Alert>
      )}
      {rerollProblem !== null && (
        <Alert color="yellow" title="The video was not started">
          {rerollProblem}
        </Alert>
      )}
      {started !== null && create.isSuccess && (
        <Alert color="green" title="Started">
          {STARTED_TEXT[started]}
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        <TalkTakeList onLoad={loadIntoForm} onReroll={reroll} rerolling={rerolling} />
      </Paper>
    </Stack>
  );
}
