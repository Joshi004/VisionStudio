import { useState } from "react";
import { Alert, Badge, Button, Group, NumberInput, SegmentedControl, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useNewestGraphicsTestCard,
  useRenderGraphicsTestCard,
  type GraphicOrientation,
  type GraphicTestCardResult,
} from "../../api/graphicsLab";
import { isJobActive } from "../../api/polling";
import { ORIENTATION_LABELS } from "./graphicsLabView";

// The limits of the server (a test card is 3 to 15 seconds at 24 frames a second).
const MIN_FRAMES = 72;
const MAX_FRAMES = 360;
const DEFAULT_FRAMES = 101;

const CHECK_LABELS: Record<string, string> = {
  frames: "Frames",
  size: "Size",
  fps: "Frame rate",
  codec: "Codec",
  pix_fmt: "Pixel format",
};

/** The checks of the render (`metrics.checks`): each is true when the video came out as asked. */
function checksOf(result: GraphicTestCardResult): [string, boolean][] {
  const metrics = result.metrics as { checks?: Record<string, unknown> } | null;
  const checks = metrics?.checks ?? {};
  return Object.entries(CHECK_LABELS).flatMap(([key]) =>
    typeof checks[key] === "boolean" ? [[key, checks[key] as boolean]] : [],
  );
}

function renderSeconds(result: GraphicTestCardResult): string | null {
  const metrics = result.metrics as { render_s?: unknown } | null;
  return typeof metrics?.render_s === "number" ? `${metrics.render_s.toFixed(1)} s` : null;
}

function fileSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(0)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * The proof that the motion service works: one button draws a test card (a deterministic video
 * with a frame counter and the safe area) and the page shows the video with the checks the
 * backend made on it. It is free; no model is called. Only the newest test card is kept.
 */
export function GraphicsTestCardPanel() {
  const [orientation, setOrientation] = useState<GraphicOrientation>("landscape");
  const [frames, setFrames] = useState<number | string>(DEFAULT_FRAMES);
  const newest = useNewestGraphicsTestCard();
  const render = useRenderGraphicsTestCard();

  const job = newest.data?.job ?? null;
  const result = newest.data?.result ?? null;
  const active = isJobActive(job);
  const framesValid = typeof frames === "number" && frames >= MIN_FRAMES && frames <= MAX_FRAMES;
  const failed = job !== null && job.status === "failed";

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Draws a test card in the motion service: a video with a frame counter, the safe area and the
        caption zone. It shows that the service is up and that the video comes out exactly as asked.
        It is free. Only the newest test card is kept.
      </Text>

      <Group align="flex-end">
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Orientation
          </Text>
          <SegmentedControl
            value={orientation}
            onChange={(value) => setOrientation(value as GraphicOrientation)}
            data={(Object.keys(ORIENTATION_LABELS) as GraphicOrientation[]).map((value) => ({
              value,
              label: ORIENTATION_LABELS[value],
            }))}
          />
        </Stack>
        <NumberInput
          label="Frames"
          description={`${MIN_FRAMES} to ${MAX_FRAMES}, at 24 a second`}
          value={frames}
          onChange={setFrames}
          min={MIN_FRAMES}
          max={MAX_FRAMES}
          allowDecimal={false}
          allowNegative={false}
          w={170}
        />
        <Button
          onClick={() => {
            if (typeof frames === "number") {
              render.mutate({ orientation, frames });
            }
          }}
          loading={render.isPending || active}
          disabled={!framesValid}
        >
          Render test card
        </Button>
      </Group>

      {render.isError && (
        <Alert color="red" title="The test card was not started">
          {describeError(render.error)}
        </Alert>
      )}
      {newest.isError && (
        <Alert color="red" title="Could not load the test card">
          {describeError(newest.error)}
        </Alert>
      )}
      {active && job !== null && (
        <Text size="sm" c="dimmed">
          {job.phase}
        </Text>
      )}
      {failed && job !== null && (
        <Alert color="red" title="The test card failed">
          {job.error ?? "The job failed."}
        </Alert>
      )}

      {result !== null && (
        <Stack gap="xs">
          <video
            controls
            preload="metadata"
            src={result.url}
            style={{
              width: "100%",
              maxWidth: result.orientation === "portrait" ? 270 : 640,
              aspectRatio: `${result.width} / ${result.height}`,
              background: "black",
            }}
          />
          <Text size="xs" c="dimmed">
            {ORIENTATION_LABELS[result.orientation]}, {result.width} x {result.height}, {result.frames}{" "}
            frames, {fileSize(result.size_bytes)}
            {renderSeconds(result) !== null ? `, drawn in ${renderSeconds(result)}` : ""}
          </Text>
          <Group gap="xs">
            {checksOf(result).map(([key, ok]) => (
              <Badge key={key} variant="light" color={ok ? "green" : "red"}>
                {CHECK_LABELS[key]}: {ok ? "as asked" : "different"}
              </Badge>
            ))}
          </Group>
          {result.warnings.map((warning) => (
            <Text key={warning} size="xs" c="orange" style={{ wordBreak: "break-word" }}>
              {warning}
            </Text>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
