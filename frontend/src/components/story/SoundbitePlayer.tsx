import { Button, Group, Stack, Text } from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";

/** Seconds of the video before and after the cut that "Play with context" adds. */
export const CONTEXT_S = 5;

type Span = { start: number; end: number };

type SoundbitePlayerProps = {
  src: string;
  // The length of the downloaded window, used until the video says its own.
  windowLength: number | null;
  // Where the quote's words are in the video (seconds), a first guide for the eye.
  quote: Span | null;
  // The cut (seconds in the video). Without it there are no "play" buttons.
  cut: Span | null;
};

function percent(value: number, total: number): string {
  return `${Math.min(100, Math.max(0, (value / total) * 100))}%`;
}

/**
 * The downloaded window of a sound bite clip as a plain video, with a bar under it that marks
 * where the quote is (yellow) and where the cut is (green), and two buttons: the cut alone, and
 * the cut with a few seconds of its surroundings. The stored file is played as it is: no render.
 */
export function SoundbitePlayer({ src, windowLength, quote, cut }: SoundbitePlayerProps) {
  const video = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const frame = useRef<number | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [position, setPosition] = useState(0);

  const total = duration ?? windowLength;

  const cancelWatch = useCallback(() => {
    stopAt.current = null;
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
  }, []);

  useEffect(() => cancelWatch, [cancelWatch]);

  const playRange = (from: number, to: number) => {
    const element = video.current;
    if (element === null) {
      return;
    }
    cancelWatch();
    element.currentTime = Math.max(0, from);
    stopAt.current = to;
    // Pauses at the end of the stretch. `timeupdate` is too coarse for a cut, so the time is
    // read on every frame while a stretch plays.
    function tick() {
      if (element === null || stopAt.current === null) {
        frame.current = null;
        return;
      }
      setPosition(element.currentTime);
      if (element.currentTime >= stopAt.current) {
        element.pause();
        cancelWatch();
        return;
      }
      frame.current = requestAnimationFrame(tick);
    }
    void element.play().then(() => {
      frame.current = requestAnimationFrame(tick);
    }, cancelWatch);
  };

  const limit = total ?? Number.POSITIVE_INFINITY;

  return (
    <Stack gap={4}>
      <video
        ref={video}
        src={src}
        controls
        preload="metadata"
        style={{ maxWidth: "100%", maxHeight: 320 }}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
        onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)}
        onPause={cancelWatch}
      />

      {total !== null && total > 0 && (
        <div
          role="img"
          aria-label="Where the quote and the cut are in the downloaded video"
          style={{
            position: "relative",
            height: 10,
            borderRadius: 5,
            background: "var(--mantine-color-gray-2)",
            overflow: "hidden",
          }}
        >
          {quote !== null && (
            <div
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                left: percent(quote.start, total),
                width: percent(Math.max(quote.end - quote.start, 0), total),
                background: "var(--mantine-color-yellow-4)",
              }}
            />
          )}
          {cut !== null && (
            <div
              style={{
                position: "absolute",
                top: 3,
                bottom: 3,
                left: percent(cut.start, total),
                width: percent(Math.max(cut.end - cut.start, 0), total),
                background: "var(--mantine-color-green-7)",
              }}
            />
          )}
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: percent(position, total),
              width: 2,
              background: "var(--mantine-color-dark-6)",
            }}
          />
        </div>
      )}
      <Text size="xs" c="dimmed">
        Yellow: where the app heard the quote. Green: the cut.
      </Text>

      {cut !== null && (
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="light"
            onClick={() => playRange(cut.start, cut.end)}
          >
            Play clip
          </Button>
          <Button
            size="compact-xs"
            variant="subtle"
            onClick={() =>
              playRange(Math.max(0, cut.start - CONTEXT_S), Math.min(limit, cut.end + CONTEXT_S))
            }
          >
            Play with context
          </Button>
        </Group>
      )}
    </Stack>
  );
}
