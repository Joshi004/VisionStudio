import { Alert, Modal, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { VoiceRecorder } from "./VoiceRecorder";

type SceneRecordingModalProps = {
  opened: boolean;
  onClose: () => void;
  sceneTitle: string;
  /** What the person reads, word for word: the scene's take text. */
  text: string;
  /** True while the recording is being sent. */
  sending: boolean;
  /** Why the last send failed, if it did. */
  error: unknown;
  onSend: (recording: Blob) => void;
};

/**
 * Records one scene (REC-003): the text to read, shown large, and the recorder. The recording
 * is read word for word, because the words are matched to the script afterwards.
 */
export function SceneRecordingModal({
  opened,
  onClose,
  sceneTitle,
  text,
  sending,
  error,
  onSend,
}: SceneRecordingModalProps) {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Record ${sceneTitle}`}
      size="lg"
      closeOnClickOutside={!sending}
      closeOnEscape={!sending}
      withCloseButton={!sending}
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Read the text below word for word. Leave a short pause at the start
          and the end.
        </Text>
        <Paper withBorder p="md" radius="sm">
          <Text size="lg" style={{ whiteSpace: "pre-wrap" }}>
            {text}
          </Text>
        </Paper>
        <VoiceRecorder busy={sending} onSend={onSend} />
        {error !== null && error !== undefined && (
          <Alert color="red" title="Could not use the recording">
            {describeError(error)}
          </Alert>
        )}
      </Stack>
    </Modal>
  );
}
