import { useRef, useState } from "react";
import {
  Alert,
  Button,
  FileButton,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useUpdateVoice,
  useUploadVoice,
  useVoices,
  VOICE_UPLOAD_MAX_MB,
  type Voice,
} from "../../api/voiceLab";
import { audioFormatLabel, formatBytes } from "../../format";
import { NAME_MAX_CHARS, TRANSCRIPT_MAX_CHARS } from "./voiceLabView";

function AddVoiceModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const upload = useUploadVoice();
  const resetFileButton = useRef<() => void>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [transcript, setTranscript] = useState("");
  const problem =
    file === null
      ? "Choose a recording."
      : name.trim() === ""
        ? "Give the voice a name."
        : transcript.trim() === ""
          ? "Write what the recording says."
          : null;

  return (
    <Modal opened={opened} onClose={onClose} title="Add a voice" size="lg">
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          A clean recording with little background noise, and what it says word for word. The
          speech model copies the voice, rhythm and style of the recording.
        </Text>
        <Group gap="sm">
          <FileButton
            resetRef={resetFileButton}
            onChange={setFile}
            accept=".wav,.mp3,.m4a,.flac,audio/*"
          >
            {(props) => (
              <Button {...props} variant="default">
                {file ? "Choose another recording" : "Choose a recording"}
              </Button>
            )}
          </FileButton>
          <Text size="xs" c="dimmed">
            {file ? file.name : `WAV, MP3, M4A or FLAC, up to ${VOICE_UPLOAD_MAX_MB} MB.`}
          </Text>
        </Group>
        <TextInput
          label="Name"
          value={name}
          maxLength={NAME_MAX_CHARS}
          onChange={(event) => setName(event.currentTarget.value)}
        />
        <Textarea
          label="What the recording says"
          description={`${transcript.trim().length} of ${TRANSCRIPT_MAX_CHARS} characters. Word for word: the server needs the exact words.`}
          value={transcript}
          onChange={(event) => setTranscript(event.currentTarget.value)}
          autosize
          minRows={3}
        />
        {upload.isError && (
          <Alert color="red" title="The voice was not saved">
            {describeError(upload.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={upload.isPending}
            disabled={problem !== null}
            onClick={() => {
              if (file !== null) {
                upload.mutate(
                  { file, name: name.trim(), transcript },
                  { onSuccess: onClose },
                );
              }
            }}
          >
            Save voice
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function EditVoiceModal({ voice, onClose }: { voice: Voice; onClose: () => void }) {
  const update = useUpdateVoice();
  const [name, setName] = useState(voice.name);
  const [transcript, setTranscript] = useState(voice.transcript);
  const problem =
    name.trim() === ""
      ? "Give the voice a name."
      : transcript.trim() === ""
        ? "Write what the recording says."
        : null;

  return (
    <Modal opened onClose={onClose} title="Edit the voice" size="lg">
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          The recording stays. A speech that is already being made keeps the transcript it
          started with.
        </Text>
        <TextInput
          label="Name"
          value={name}
          maxLength={NAME_MAX_CHARS}
          onChange={(event) => setName(event.currentTarget.value)}
        />
        <Textarea
          label="What the recording says"
          description={`${transcript.trim().length} of ${TRANSCRIPT_MAX_CHARS} characters.`}
          value={transcript}
          onChange={(event) => setTranscript(event.currentTarget.value)}
          autosize
          minRows={3}
        />
        {update.isError && (
          <Alert color="red" title="The voice was not saved">
            {describeError(update.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={update.isPending}
            disabled={problem !== null}
            onClick={() =>
              update.mutate(
                { voiceId: voice.id, body: { name: name.trim(), transcript } },
                { onSuccess: onClose },
              )
            }
          >
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** The saved voices: listen, add one from a recording, change a name or a transcript. */
export function VoiceLibrary() {
  const voices = useVoices();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Voice | null>(null);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text size="sm" fw={600}>
          Saved voices
        </Text>
        <Button size="compact-sm" variant="default" onClick={() => setAdding(true)}>
          Add a voice
        </Button>
      </Group>
      {voices.isLoading && <Loader size="sm" />}
      {voices.isError && (
        <Alert color="red" title="Could not load the voices">
          {describeError(voices.error)}
        </Alert>
      )}
      {voices.data && voices.data.length === 0 && (
        <Text size="sm" c="dimmed">
          No saved voices yet. Add a recording, or save a speech from a run below.
        </Text>
      )}
      {voices.data?.map((voice) => (
        <Paper key={voice.id} withBorder p="sm" radius="md">
          <Stack gap={4}>
            <Group justify="space-between" wrap="nowrap">
              <Text size="sm" fw={600}>
                {voice.name}
              </Text>
              <Button size="compact-xs" variant="subtle" onClick={() => setEditing(voice)}>
                Edit
              </Button>
            </Group>
            <audio
              key={voice.id}
              src={voice.url}
              controls
              preload="metadata"
              style={{ width: "100%" }}
            />
            <Text size="xs" c="dimmed">
              {audioFormatLabel(voice.mime)} · {voice.duration_s.toFixed(1)} s ·{" "}
              {formatBytes(voice.size_bytes)} ·{" "}
              {voice.origin === "upload" ? "uploaded" : "made in the Voice lab"}
            </Text>
            <Text size="xs" c="dimmed" lineClamp={3} title={voice.transcript}>
              “{voice.transcript}”
            </Text>
          </Stack>
        </Paper>
      ))}
      {adding && <AddVoiceModal opened onClose={() => setAdding(false)} />}
      {editing !== null && (
        <EditVoiceModal key={editing.id} voice={editing} onClose={() => setEditing(null)} />
      )}
    </Stack>
  );
}
