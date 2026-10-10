import { useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text, TextInput, Textarea } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useSaveRunAsVoice, type VoiceLabRun } from "../../api/voiceLab";
import { NAME_MAX_CHARS, TRANSCRIPT_MAX_CHARS } from "./voiceLabView";

type SaveVoiceModalProps = {
  run: VoiceLabRun;
  opened: boolean;
  onClose: () => void;
};

/**
 * Saves the speech of a run as a voice. The transcript starts as the run's text, which is what
 * the speech says; change it if the speech does not say exactly that.
 */
export function SaveVoiceModal({ run, opened, onClose }: SaveVoiceModalProps) {
  const save = useSaveRunAsVoice();
  const [name, setName] = useState("");
  const [transcript, setTranscript] = useState(run.text);
  const problem =
    name.trim() === ""
      ? "Give the voice a name."
      : transcript.trim() === ""
        ? "Write what the speech says."
        : null;

  return (
    <Modal opened={opened} onClose={onClose} title="Save as a voice" size="lg">
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          A saved voice can read any text in Clone and Direction mode, and can speak a project's
          script. The server needs the exact words of the recording.
        </Text>
        <TextInput
          label="Name"
          value={name}
          maxLength={NAME_MAX_CHARS}
          onChange={(event) => setName(event.currentTarget.value)}
          data-autofocus
        />
        <Textarea
          label="What the speech says"
          description={`${transcript.trim().length} of ${TRANSCRIPT_MAX_CHARS} characters.`}
          value={transcript}
          onChange={(event) => setTranscript(event.currentTarget.value)}
          autosize
          minRows={3}
        />
        {save.isError && (
          <Alert color="red" title="The voice was not saved">
            {describeError(save.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            disabled={problem !== null}
            onClick={() =>
              save.mutate(
                { runId: run.id, name: name.trim(), transcript },
                { onSuccess: onClose },
              )
            }
          >
            Save voice
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
