import { useEffect, useRef, useState } from "react";
import { Alert, Button, Group, Stack, Text } from "@mantine/core";

type VoiceRecorderProps = {
  /** True while a recording is being sent: nothing can be recorded or sent then. */
  busy: boolean;
  /** Called with the recording when the person presses Send. */
  onSend: (recording: Blob) => void;
};

type Clip = { blob: Blob; url: string };

/** The formats tried in order. Chrome and Firefox record WebM, Safari records MP4. */
const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

/**
 * The raw voice: the browser must not process it (REC-001's decision), because gain control and
 * noise suppression make a voice pump or sound processed.
 */
const AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false,
  channelCount: 1,
};

const UPDATE_MS = 250;

function formatTime(seconds: number): string {
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, "0")}`;
}

/**
 * Records the voice from the microphone: Record, Stop, listen back, Record again or Send
 * (REC-003). It only makes the audio; the page that uses it says what to read and sends the
 * file. The microphone is released as soon as the recording stops, and when this component goes
 * away.
 */
export function VoiceRecorder({ busy, onSend }: VoiceRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [clip, setClip] = useState<Clip | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<number | null>(null);
  const clipUrl = useRef<string | null>(null);

  function releaseMicrophone() {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
  }

  function forgetClip() {
    if (clipUrl.current !== null) {
      URL.revokeObjectURL(clipUrl.current);
      clipUrl.current = null;
    }
    setClip(null);
  }

  // When the component goes away: stop recording without keeping anything, free the microphone
  // and the playback URL.
  useEffect(
    () => () => {
      const active = recorder.current;
      if (active !== null) {
        active.onstop = null;
        if (active.state !== "inactive") {
          active.stop();
        }
      }
      stream.current?.getTracks().forEach((track) => track.stop());
      if (timer.current !== null) {
        window.clearInterval(timer.current);
      }
      if (clipUrl.current !== null) {
        URL.revokeObjectURL(clipUrl.current);
      }
    },
    [],
  );

  async function start() {
    setProblem(null);
    if (
      typeof MediaRecorder === "undefined" ||
      navigator.mediaDevices?.getUserMedia === undefined
    ) {
      setProblem(
        "The browser allows the microphone only on https or localhost. Upload a file instead.",
      );
      return;
    }
    let media: MediaStream;
    try {
      media = await navigator.mediaDevices.getUserMedia({
        audio: AUDIO_CONSTRAINTS,
      });
    } catch {
      setProblem(
        "The microphone could not be used. Allow it in the browser and try again.",
      );
      return;
    }
    forgetClip();
    const mimeType = MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
    let active: MediaRecorder;
    try {
      active = new MediaRecorder(media, mimeType ? { mimeType } : undefined);
    } catch {
      media.getTracks().forEach((track) => track.stop());
      setProblem("This browser cannot record audio. Upload a file instead.");
      return;
    }
    const parts: Blob[] = [];
    active.ondataavailable = (event) => {
      if (event.data.size > 0) {
        parts.push(event.data);
      }
    };
    active.onstop = () => {
      releaseMicrophone();
      setRecording(false);
      const blob = new Blob(parts, { type: active.mimeType });
      if (blob.size === 0) {
        setProblem("Nothing was recorded. Check the microphone and try again.");
        return;
      }
      const url = URL.createObjectURL(blob);
      clipUrl.current = url;
      setClip({ blob, url });
    };
    stream.current = media;
    recorder.current = active;
    const startedAt = Date.now();
    setSeconds(0);
    timer.current = window.setInterval(
      () => setSeconds((Date.now() - startedAt) / 1000),
      UPDATE_MS,
    );
    active.start();
    setRecording(true);
  }

  function stop() {
    if (recorder.current?.state === "recording") {
      recorder.current.stop();
    }
  }

  return (
    <Stack gap="xs">
      {problem !== null && (
        <Alert color="red" title="Could not record">
          {problem}
        </Alert>
      )}
      {recording ? (
        <Group gap="sm">
          <Text size="sm" c="red" fw={600}>
            Recording {formatTime(seconds)}
          </Text>
          <Button color="red" onClick={stop}>
            Stop
          </Button>
        </Group>
      ) : clip !== null ? (
        <Stack gap="xs">
          <audio
            src={clip.url}
            controls
            style={{ width: "100%", maxWidth: 420 }}
          />
          <Group gap="sm">
            <Button
              variant="default"
              disabled={busy}
              onClick={() => void start()}
            >
              Record again
            </Button>
            <Button loading={busy} onClick={() => onSend(clip.blob)}>
              Send
            </Button>
          </Group>
        </Stack>
      ) : (
        <Group gap="sm">
          <Button disabled={busy} onClick={() => void start()}>
            Record
          </Button>
        </Group>
      )}
    </Stack>
  );
}
