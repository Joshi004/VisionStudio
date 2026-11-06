import { Fragment } from "react";
import {
  Alert,
  Divider,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import type { FullScript } from "../../api/voiceRecordings";
import { VoiceRecorder } from "./VoiceRecorder";

type FullRecordingModalProps = {
  opened: boolean;
  onClose: () => void;
  script: FullScript;
  /** True while the recording is being sent. */
  sending: boolean;
  /** Why the last send failed, if it did. */
  error: unknown;
  onSend: (recording: Blob) => void;
};

/**
 * Records the whole video in one flow (REC-004): the script of every scene in order, with a
 * marker at the start of each scene and a pause sign at every scene change, and the recorder.
 * The recording is read word for word, because the words are matched to the script afterwards,
 * and the app finds where each scene begins from the pauses.
 */
export function FullRecordingModal({
  opened,
  onClose,
  script,
  sending,
  error,
  onSend,
}: FullRecordingModalProps) {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Record the whole video"
      size="xl"
      closeOnClickOutside={!sending}
      closeOnEscape={!sending}
      withCloseButton={!sending}
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Read the whole script below word for word, in one go. Pause clearly at
          every pause sign, where the scene changes: the recording is cut there
          into one take for each scene. Leave a short pause at the start and the
          end.
        </Text>
        <VoiceRecorder busy={sending} onSend={onSend} />
        {error !== null && error !== undefined && (
          <Alert color="red" title="Could not use the recording">
            {describeError(error)}
          </Alert>
        )}
        <Paper withBorder p="md" radius="sm">
          <ScrollArea.Autosize mah={420}>
            <Stack gap="xs">
              {script.scenes.map((scene, position) => (
                <Fragment key={scene.scene_id}>
                  {position > 0 && (
                    <Divider label="Pause" labelPosition="center" my="xs" />
                  )}
                  <Text size="xs" c="dimmed" fw={600} tt="uppercase">
                    Scene {scene.index ?? position + 1}
                  </Text>
                  <Text size="lg" style={{ whiteSpace: "pre-wrap" }}>
                    {scene.text}
                  </Text>
                </Fragment>
              ))}
            </Stack>
          </ScrollArea.Autosize>
        </Paper>
      </Stack>
    </Modal>
  );
}
