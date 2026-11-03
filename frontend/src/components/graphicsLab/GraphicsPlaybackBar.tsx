import { Button, Group, Paper, Slider, Stack, Switch, Text } from "@mantine/core";

import { beatFrames } from "./graphicsLabView";
import type { SyncedVideos } from "./useSyncedVideos";
import type { GraphicResolved } from "../../api/graphicsLab";

type GraphicsPlaybackBarProps = {
  sync: SyncedVideos;
  resolved: GraphicResolved | null;
  frames: number;
  fps: number;
  /** False while no card has a video. */
  hasVideos: boolean;
  showSafeArea: boolean;
  onShowSafeArea: (show: boolean) => void;
  showCaptionArea: boolean;
  onShowCaptionArea: (show: boolean) => void;
};

/**
 * The one control of the comparison: play, pause, step a frame, jump to a beat and seek, for every
 * video at once, and the switches of the two overlays. It stays at the top of the screen while the
 * cards below are read.
 */
export function GraphicsPlaybackBar({
  sync,
  resolved,
  frames,
  fps,
  hasVideos,
  showSafeArea,
  onShowSafeArea,
  showCaptionArea,
  onShowCaptionArea,
}: GraphicsPlaybackBarProps) {
  const beats = beatFrames(resolved);
  const previousBeat = [...beats].reverse().find((beat) => beat < sync.frame);
  const nextBeat = beats.find((beat) => beat > sync.frame);

  return (
    <Paper
      withBorder
      p="xs"
      radius="md"
      style={{ position: "sticky", top: "var(--app-shell-header-offset, 0px)", zIndex: 10 }}
    >
      <Stack gap="xs">
        <Group gap="xs" wrap="wrap">
          <Button
            size="compact-sm"
            onClick={sync.playing ? sync.pause : sync.play}
            disabled={!hasVideos}
          >
            {sync.playing ? "Pause" : "Play"}
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            onClick={() => sync.step(-1)}
            disabled={!hasVideos}
            aria-label="Back one frame"
          >
            ◀ Frame
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            onClick={() => sync.step(1)}
            disabled={!hasVideos}
            aria-label="Forward one frame"
          >
            Frame ▶
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            onClick={() => previousBeat !== undefined && sync.seekFrame(previousBeat)}
            disabled={!hasVideos || previousBeat === undefined}
          >
            ◀ Beat
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            onClick={() => nextBeat !== undefined && sync.seekFrame(nextBeat)}
            disabled={!hasVideos || nextBeat === undefined}
          >
            Beat ▶
          </Button>
          <Text size="sm" data-testid="playback-position" style={{ fontVariantNumeric: "tabular-nums" }}>
            Frame {sync.frame + 1} of {frames}, {(sync.frame / fps).toFixed(2)} s
          </Text>
          <Group gap="md" ml="auto">
            <Switch
              size="xs"
              label="Safe area"
              checked={showSafeArea}
              onChange={(event) => onShowSafeArea(event.currentTarget.checked)}
            />
            <Switch
              size="xs"
              label="Caption area"
              checked={showCaptionArea}
              onChange={(event) => onShowCaptionArea(event.currentTarget.checked)}
            />
          </Group>
        </Group>
        <Slider
          min={0}
          max={Math.max(frames - 1, 1)}
          step={1}
          value={sync.frame}
          onChange={sync.seekFrame}
          disabled={!hasVideos}
          label={(value) => `${(value / fps).toFixed(1)} s`}
          marks={beats.map((value) => ({ value }))}
          size="sm"
          mb={6}
          aria-label="Position in the graphic"
        />
      </Stack>
    </Paper>
  );
}
