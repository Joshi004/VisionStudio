import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { uploadError } from "../../api/projects";
import {
  PREVIEW_SPAN_S,
  recordingExcerptUrl,
  type SceneBoundary,
} from "../../api/voiceRecordings";

/** The server gives at most 10 seconds at a time; stay a little under it. */
const MAX_SHOWN_S = 9.99;
/** How much of the recording is shown either side of the window the cut may be in. */
const CONTEXT_S = 1;
const CANVAS_WIDTH = 800;
const CANVAS_HEIGHT = 140;
/** One arrow key press moves the cut by this much; with Shift, ten times as much. */
const KEY_STEP_S = 0.005;

type BoundaryCutModalProps = {
  opened: boolean;
  onClose: () => void;
  projectId: number;
  recordingId: number;
  boundary: SceneBoundary;
  /** "Scene 3 to Scene 4". */
  title: string;
  /** True while the cut point is being saved. */
  saving: boolean;
  /** Why the last save failed, if it did. */
  error: unknown;
  onSave: (cutS: number) => void;
};

function toMillis(seconds: number): number {
  return Math.round(seconds * 1000) / 1000;
}

/**
 * The part of the recording that is shown: a second either side of the window the cut may be in,
 * kept to what the server gives and to the start of the recording.
 */
function shownRange(boundary: SceneBoundary): { start: number; end: number } {
  let start = Math.max(0, boundary.min_cut_s - CONTEXT_S);
  let end = boundary.max_cut_s + CONTEXT_S;
  if (end - start > MAX_SHOWN_S) {
    start = Math.max(0, boundary.final_cut_s - MAX_SHOWN_S / 2);
    end = start + MAX_SHOWN_S;
  }
  return { start: toMillis(start), end: toMillis(end) };
}

type CutEditorProps = Pick<
  BoundaryCutModalProps,
  "projectId" | "recordingId" | "boundary" | "saving" | "onSave" | "onClose"
>;

/**
 * Draws the part of the recording around a tight boundary and lets the person drag the cut
 * point inside the window where no word of either scene would be cut off. The audio is decoded
 * in the browser (Web Audio), so the two previews play exactly what each scene would hold.
 * Mounted only while the modal is open, so each opening starts fresh.
 */
function CutEditor({
  projectId,
  recordingId,
  boundary,
  saving,
  onSave,
  onClose,
}: CutEditorProps) {
  const { start, end } = shownRange(boundary);
  const url = recordingExcerptUrl(projectId, recordingId, start, end);
  const [audio, setAudio] = useState<AudioBuffer | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Where the cut may be: the boundary's window, kept to what is shown.
  const windowStart = Math.max(boundary.min_cut_s, start);
  const windowEnd = Math.min(
    boundary.max_cut_s,
    audio === null ? end : start + audio.duration,
  );
  const [cut, setCut] = useState(() =>
    Math.min(
      Math.max(boundary.final_cut_s, Math.max(boundary.min_cut_s, start)),
      Math.min(boundary.max_cut_s, end),
    ),
  );
  const context = useRef<AudioContext | null>(null);
  const playing = useRef<AudioBufferSourceNode | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const track = useRef<HTMLDivElement | null>(null);

  // Loads and decodes the part of the recording.
  useEffect(() => {
    const abort = new AbortController();
    const audioContext = new AudioContext();
    context.current = audioContext;
    void (async () => {
      try {
        const response = await fetch(url, { signal: abort.signal });
        if (!response.ok) {
          throw await uploadError(response);
        }
        const decoded = await audioContext.decodeAudioData(
          await response.arrayBuffer(),
        );
        if (!abort.signal.aborted) {
          setAudio(decoded);
        }
      } catch (problem) {
        if (!abort.signal.aborted) {
          setLoadError(describeError(problem));
        }
      }
    })();
    return () => {
      abort.abort();
      playing.current?.stop();
      playing.current = null;
      context.current = null;
      void audioContext.close();
    };
  }, [url]);

  // Draws the waveform: the window the cut may be in is shaded, and the loudest and quietest
  // sample of each column is a bar.
  useEffect(() => {
    const element = canvas.current;
    const drawing = element?.getContext("2d");
    if (element === null || !drawing || audio === null) {
      return;
    }
    const samples = audio.getChannelData(0);
    const middle = CANVAS_HEIGHT / 2;
    const seconds = audio.duration;
    drawing.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    const shadeFrom = ((windowStart - start) / seconds) * CANVAS_WIDTH;
    const shadeTo = ((windowEnd - start) / seconds) * CANVAS_WIDTH;
    drawing.fillStyle = "rgba(34, 139, 230, 0.18)";
    drawing.fillRect(shadeFrom, 0, Math.max(1, shadeTo - shadeFrom), CANVAS_HEIGHT);
    drawing.fillStyle = "#868e96";
    for (let column = 0; column < CANVAS_WIDTH; column += 1) {
      const from = Math.floor((column / CANVAS_WIDTH) * samples.length);
      const to = Math.max(
        from + 1,
        Math.floor(((column + 1) / CANVAS_WIDTH) * samples.length),
      );
      let low = 0;
      let high = 0;
      for (let index = from; index < to && index < samples.length; index += 1) {
        low = Math.min(low, samples[index]);
        high = Math.max(high, samples[index]);
      }
      drawing.fillRect(
        column,
        middle - high * middle,
        1,
        Math.max(1, (high - low) * middle),
      );
    }
  }, [audio, start, windowStart, windowEnd]);

  /** The cut point nearest to a time, inside the window, to the millisecond. */
  function clampCut(seconds: number): number {
    return Math.min(Math.max(toMillis(seconds), windowStart), windowEnd);
  }

  function moveToPixel(clientX: number) {
    const box = track.current?.getBoundingClientRect();
    if (!box || box.width === 0 || audio === null) {
      return;
    }
    setCut(clampCut(start + ((clientX - box.left) / box.width) * audio.duration));
  }

  function stopPlayback() {
    playing.current?.stop();
    playing.current = null;
  }

  /** Plays `length` seconds of the part from `offset` seconds into it. */
  function play(offset: number, length: number) {
    const audioContext = context.current;
    if (audioContext === null || audio === null || length <= 0) {
      return;
    }
    stopPlayback();
    void audioContext.resume();
    const source = audioContext.createBufferSource();
    source.buffer = audio;
    source.connect(audioContext.destination);
    source.onended = () => {
      if (playing.current === source) {
        playing.current = null;
      }
    };
    playing.current = source;
    source.start(0, offset, length);
  }

  const position = cut - start;
  const seconds = audio?.duration ?? 1;

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Drag the marker to where the scene should end. The blue area is where
        the cut can be without cutting off a word of either scene. Listen to
        both sides before you save.
      </Text>
      <Text size="sm">
        …{boundary.before_words}{" "}
        <Text span c="dimmed">
          |
        </Text>{" "}
        {boundary.after_words}…
      </Text>
      {audio === null && loadError === null && <Loader size="sm" />}
      {loadError !== null && (
        <Alert color="red" title="Could not load the recording">
          {loadError}
        </Alert>
      )}
      {audio !== null && (
        <div
          ref={track}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            moveToPixel(event.clientX);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              moveToPixel(event.clientX);
            }
          }}
          style={{
            position: "relative",
            width: "100%",
            touchAction: "none",
            cursor: "ew-resize",
            border: "1px solid var(--mantine-color-default-border)",
            borderRadius: 4,
          }}
        >
          <canvas
            ref={canvas}
            width={CANVAS_WIDTH}
            height={CANVAS_HEIGHT}
            style={{ display: "block", width: "100%", height: CANVAS_HEIGHT }}
          />
          <div
            role="slider"
            tabIndex={0}
            aria-label="Cut point"
            aria-valuemin={windowStart}
            aria-valuemax={windowEnd}
            aria-valuenow={cut}
            onKeyDown={(event) => {
              const step = event.shiftKey ? KEY_STEP_S * 10 : KEY_STEP_S;
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                setCut(clampCut(cut - step));
              } else if (event.key === "ArrowRight") {
                event.preventDefault();
                setCut(clampCut(cut + step));
              }
            }}
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${(position / seconds) * 100}%`,
              width: 3,
              marginLeft: -1,
              background: "var(--mantine-color-red-6)",
            }}
          />
        </div>
      )}
      <Text size="sm">
        Cut point: <b>{cut.toFixed(3)} s</b>{" "}
        <Text span size="xs" c="dimmed">
          (allowed from {windowStart.toFixed(3)} to {windowEnd.toFixed(3)} s)
        </Text>
      </Text>
      <Group gap="xs">
        <Button
          size="compact-sm"
          variant="default"
          disabled={audio === null}
          onClick={() => {
            const offset = Math.max(0, position - PREVIEW_SPAN_S);
            play(offset, position - offset);
          }}
        >
          Play before the cut
        </Button>
        <Button
          size="compact-sm"
          variant="default"
          disabled={audio === null}
          onClick={() =>
            play(
              position,
              Math.min(PREVIEW_SPAN_S, (audio?.duration ?? 0) - position),
            )
          }
        >
          Play after the cut
        </Button>
      </Group>
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button
          loading={saving}
          disabled={audio === null}
          onClick={() => onSave(cut)}
        >
          Save cut point
        </Button>
      </Group>
    </Stack>
  );
}

/**
 * Sets the cut point of a tight scene boundary by hand (REC-005): a waveform of the recording
 * around the boundary, a marker that can be dragged only inside the window where no word is cut
 * off, and a preview of both sides of the cut.
 */
export function BoundaryCutModal({
  opened,
  onClose,
  title,
  error,
  ...editor
}: BoundaryCutModalProps) {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Set the cut point: ${title}`}
      size="xl"
      closeOnClickOutside={!editor.saving}
      closeOnEscape={!editor.saving}
      withCloseButton={!editor.saving}
    >
      <Stack gap="md">
        {error !== null && error !== undefined && (
          <Alert color="red" title="Could not save the cut point">
            {describeError(error)}
          </Alert>
        )}
        <CutEditor {...editor} onClose={onClose} />
      </Stack>
    </Modal>
  );
}
