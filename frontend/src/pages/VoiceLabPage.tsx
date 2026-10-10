import { useState } from "react";
import { Alert, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../api/errors";
import { useCreateVoiceLabRun, useVoices, type VoiceLabRun } from "../api/voiceLab";
import { LicenseNotice } from "../components/voiceLab/LicenseNotice";
import { VoiceLabForm } from "../components/voiceLab/VoiceLabForm";
import { VoiceLabRunList } from "../components/voiceLab/VoiceLabRunList";
import { VoiceLibrary } from "../components/voiceLab/VoiceLibrary";
import {
  DEFAULT_FORM,
  stateFromRun,
  toRequest,
  type VoiceLabFormState,
} from "../components/voiceLab/voiceLabView";

/**
 * A page for trying Breeze TTS: a voice made from a description, a saved voice reading a text,
 * or a saved voice steered by an instruction. Each run is a paid GPU job of one to three
 * minutes. A speech can be saved as a voice, and a saved voice can speak a project's script.
 * It belongs to no project and changes none.
 */
export function VoiceLabPage() {
  const [form, setForm] = useState<VoiceLabFormState>(DEFAULT_FORM);
  const create = useCreateVoiceLabRun();
  const voices = useVoices();

  function loadIntoForm(run: VoiceLabRun) {
    setForm(stateFromRun(run));
  }

  return (
    <Stack gap="lg" maw={1100}>
      <Stack gap={4}>
        <Title order={2}>Voice lab</Title>
        <Text size="sm" c="dimmed">
          Try Breeze TTS 2, the speech model on the GPU server, in English or Chinese. Describe a
          voice and the model invents it, or choose a saved voice (a clean recording and its exact
          words) and the model reads your text in it. Each run is a paid GPU job of one to three
          minutes, and it belongs to no project.
        </Text>
        <LicenseNotice />
      </Stack>

      <Paper withBorder p="md" radius="md">
        <VoiceLabForm
          state={form}
          onChange={setForm}
          onRun={() => create.mutate(toRequest(form))}
          running={create.isPending}
          voices={voices.data ?? []}
        />
      </Paper>

      {create.isError && (
        <Alert color="red" title="The run was not started">
          {describeError(create.error)}
        </Alert>
      )}
      {create.isSuccess && (
        <Alert color="green" title="Started">
          The run is waiting for a free GPU slot and will appear below. You can leave this page: it
          keeps going.
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        <VoiceLibrary />
      </Paper>

      <Paper withBorder p="md" radius="md">
        <VoiceLabRunList onLoad={loadIntoForm} />
      </Paper>
    </Stack>
  );
}
