import { Fragment } from "react";
import {
  Alert,
  Button,
  Divider,
  FileButton,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import type { PatchRegion } from "../../api/voiceRecordings";
import { VoiceRecorder } from "./VoiceRecorder";

type PatchRecordingModalProps = {
  opened: boolean;
  onClose: () => void;
  /** The part to record again, with the text around it. */
  region: PatchRegion;
  /** What the part is called, for example "Scene 3 to Scene 4". */
  title: string;
  /** True while a recording is being sent. */
  sending: boolean;
  /** Why the last send failed, if it did. */
  error: unknown;
  onSend: (recording: Blob) => void;
  onUpload: (file: File) => void;
};

/** The files a recording may be: the server decides by what is inside, not by the name. */
const RECORDING_ACCEPT = ".wav,.mp3,.webm,.m4a,.mp4,audio/*";

/**
 * Records one part of the whole recording again (REC-006): the words to read, highlighted in the
 * text around them, with a pause sign at every scene change inside them, and the recorder. The
 * part is read word for word, with a clear pause at each pause sign and a short silence at the
 * start and the end. The part replaces the stretch it covers when the parts are spliced in.
 */
export function PatchRecordingModal({
  opened,
  onClose,
  region,
  title,
  sending,
  error,
  onSend,
  onUpload,
}: PatchRecordingModalProps) {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Record ${title} again`}
      size="xl"
      closeOnClickOutside={!sending}
      closeOnEscape={!sending}
      withCloseButton={!sending}
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Read only the highlighted words, word for word, in the same place and
          with the same microphone as the rest. Pause clearly at every pause
          sign, and leave a short silence before the first word and after the
          last. The grey text is only there to show where it fits.
        </Text>
        <VoiceRecorder busy={sending} onSend={onSend} />
        <Group>
          <FileButton
            onChange={(file) => {
              if (file !== null) {
                onUpload(file);
              }
            }}
            accept={RECORDING_ACCEPT}
          >
            {(props) => (
              <Button
                {...props}
                size="compact-sm"
                variant="default"
                loading={sending}
              >
                Upload a file instead
              </Button>
            )}
          </FileButton>
        </Group>
        {error !== null && error !== undefined && (
          <Alert color="red" title="Could not use the recording">
            {describeError(error)}
          </Alert>
        )}
        <Paper withBorder p="md" radius="sm">
          <Stack gap="xs">
            {region.before_context !== "" && (
              <Text size="md" c="dimmed">
                …{region.before_context}
              </Text>
            )}
            {region.parts.map((part, position) => (
              <Fragment key={position}>
                {position > 0 && (
                  <Divider label="Pause" labelPosition="center" my="xs" />
                )}
                <Text
                  size="lg"
                  fw={600}
                  style={{
                    whiteSpace: "pre-wrap",
                    background: "var(--mantine-color-yellow-light)",
                    padding: "2px 6px",
                    borderRadius: 4,
                  }}
                >
                  {part}
                </Text>
              </Fragment>
            ))}
            {region.after_context !== "" && (
              <Text size="md" c="dimmed">
                {region.after_context}…
              </Text>
            )}
          </Stack>
        </Paper>
      </Stack>
    </Modal>
  );
}
