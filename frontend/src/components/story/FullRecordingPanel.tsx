import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  FileButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useFullRecording,
  useRetryFullRecording,
  useUploadFullRecording,
  type FullRecordingState,
  type FullScript,
  type RecordingOrigin,
} from "../../api/voiceRecordings";
import { FullRecordingModal } from "./FullRecordingModal";

type FullRecordingPanelProps = {
  projectId: number;
};

/** The files a recording may be: the server decides by what is inside, not by the name. */
const RECORDING_ACCEPT = ".wav,.mp3,.webm,.m4a,.mp4,audio/*";

const STAGE: Record<
  FullRecordingState["stage"],
  { label: string; color: string }
> = {
  transcribing: { label: "Being transcribed", color: "blue" },
  transcription_failed: { label: "Transcription failed", color: "red" },
  refused: { label: "Refused", color: "red" },
  tight: { label: "Tight scene boundaries", color: "yellow" },
  splitting: { label: "Being split into scenes", color: "blue" },
  split_failed: { label: "Not split", color: "red" },
  split: { label: "Split into scenes", color: "green" },
};

function formatLength(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** "Scene 3", from the script's own numbering. */
function sceneName(script: FullScript, sceneId: string): string {
  const position = script.scenes.findIndex(
    (scene) => scene.scene_id === sceneId,
  );
  if (position < 0) {
    return "a scene";
  }
  return `Scene ${script.scenes[position].index ?? position + 1}`;
}

/**
 * Recording the whole video in one flow (REC-004): the person records it in the browser or
 * uploads a file, the app transcribes it, finds the scene boundaries and, when every boundary is
 * clean, splits it into one take for each scene. This panel shows where the newest full
 * recording stands and lists the tight boundaries (read only for now).
 */
export function FullRecordingPanel({ projectId }: FullRecordingPanelProps) {
  const { data, isLoading, isError, error } = useFullRecording(projectId, true);
  // Two mutations so that each one's error shows where the person is looking.
  const sendFile = useUploadFullRecording(projectId);
  const sendRecording = useUploadFullRecording(projectId);
  const retry = useRetryFullRecording(projectId);
  const [recordingOpen, setRecordingOpen] = useState(false);

  const sending = sendFile.isPending || sendRecording.isPending;
  const script = data?.script;
  const newest = data?.newest ?? null;
  const canRecord =
    script !== undefined && script.blocked_reason === null && !sending;

  function send(origin: RecordingOrigin, file: Blob, done?: () => void) {
    if (script === undefined) {
      return;
    }
    const mutation = origin === "upload" ? sendFile : sendRecording;
    mutation.mutate(
      { scriptKey: script.script_key, origin, file },
      { onSuccess: done },
    );
  }

  return (
    <Paper withBorder p="sm" radius="sm">
      <Stack gap="xs">
        <Text fw={600} size="sm">
          Record the whole video
        </Text>
        <Text size="xs" c="dimmed">
          Read the whole script in one go, in the browser or from a file. The
          app finds where each scene begins from your pauses and cuts the
          recording into one take for each scene. Or record scene by scene
          below.
        </Text>
        {isLoading && <Loader size="xs" />}
        {isError && (
          <Alert color="red" title="Could not load the full recording">
            {describeError(error)}
          </Alert>
        )}
        {script?.blocked_reason != null && (
          <Text size="xs" c="dimmed">
            {script.blocked_reason}
          </Text>
        )}
        <Group gap="xs">
          <Button
            size="compact-sm"
            disabled={!canRecord}
            onClick={() => {
              sendRecording.reset();
              setRecordingOpen(true);
            }}
          >
            {newest === null ? "Record the whole video" : "Record it again"}
          </Button>
          <FileButton
            onChange={(file) => {
              if (file !== null) {
                send("upload", file);
              }
            }}
            accept={RECORDING_ACCEPT}
          >
            {(props) => (
              <Button
                {...props}
                size="compact-sm"
                variant="default"
                loading={sendFile.isPending}
                disabled={!canRecord}
              >
                Upload the whole video
              </Button>
            )}
          </FileButton>
        </Group>
        {sendFile.isError && (
          <Alert color="red" title="Could not use the file">
            {describeError(sendFile.error)}
          </Alert>
        )}
        {retry.isError && (
          <Alert color="red" title="Could not try again">
            {describeError(retry.error)}
          </Alert>
        )}
        {newest !== null && script !== undefined && (
          <Stack gap={4}>
            <Group gap="xs" align="center">
              <Badge variant="light" color={STAGE[newest.stage].color}>
                {STAGE[newest.stage].label}
              </Badge>
              <Text size="xs" c="dimmed">
                Version {newest.version}, {formatLength(newest.duration_s)}
              </Text>
              {newest.can_retry && (
                <Button
                  size="compact-xs"
                  variant="default"
                  loading={retry.isPending}
                  onClick={() => retry.mutate(newest.recording_id)}
                >
                  {newest.stage === "split_failed" ? "Split now" : "Try again"}
                </Button>
              )}
            </Group>
            {newest.stage !== "split" && (
              <Text
                size="xs"
                c={
                  newest.stage === "transcribing" ||
                  newest.stage === "splitting"
                    ? "dimmed"
                    : "red"
                }
              >
                {newest.message}
              </Text>
            )}
            {newest.script_changed && (
              <Text size="xs" c="yellow.8">
                The script was changed after this was recorded. A scene whose
                text changed has to be recorded again.
              </Text>
            )}
            {newest.stage === "tight" && (
              <Text size="xs" c="dimmed">
                A tight boundary has too little pause to cut at, or a word next
                to it was not heard. Record the whole video again with a clear
                pause at the scene changes, or record the scenes separately.
                Deciding them here comes in a later step.
              </Text>
            )}
            {newest.boundaries
              .filter((boundary) => boundary.tight)
              .map((boundary) => (
                <Paper
                  key={`${boundary.after_scene_id}/${boundary.before_scene_id}`}
                  withBorder
                  p="xs"
                  radius="sm"
                >
                  <Stack gap={2}>
                    <Text size="xs" fw={600}>
                      {sceneName(script, boundary.after_scene_id)} to{" "}
                      {sceneName(script, boundary.before_scene_id)}, pause{" "}
                      {Math.round(boundary.pause_s * 1000)} ms
                    </Text>
                    <Text size="xs">
                      …{boundary.before_words}{" "}
                      <Text span c="dimmed">
                        |
                      </Text>{" "}
                      {boundary.after_words}…
                    </Text>
                    {boundary.reasons.map((reason) => (
                      <Text key={reason} size="xs" c="yellow.8">
                        {reason}
                      </Text>
                    ))}
                  </Stack>
                </Paper>
              ))}
          </Stack>
        )}
      </Stack>
      {script !== undefined && (
        <FullRecordingModal
          opened={recordingOpen}
          onClose={() => setRecordingOpen(false)}
          script={script}
          sending={sendRecording.isPending}
          error={sendRecording.error}
          onSend={(recording) =>
            send("browser", recording, () => setRecordingOpen(false))
          }
        />
      )}
    </Paper>
  );
}
