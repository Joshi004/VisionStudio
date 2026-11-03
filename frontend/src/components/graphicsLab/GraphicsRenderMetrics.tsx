import { Badge, Group, Stack, Text } from "@mantine/core";

import type { GraphicRender } from "../../api/graphicsLab";
import {
  CHECK_LABELS,
  callText,
  formatBytes,
  readMetrics,
  repeatText,
  TIMING_SOURCE_LABELS,
} from "./graphicsLabView";

/** The warnings of a render come from the backend as a list of strings. */
function warningsOf(render: Pick<GraphicRender, "warnings">): string[] {
  return Array.isArray(render.warnings)
    ? render.warnings.filter((warning): warning is string => typeof warning === "string")
    : [];
}

/**
 * What was measured on one render (§4.7): the five checks on the video, how long it took to
 * draw and how large it is, what the model call cost, whether a repeat matched, and the
 * warnings (the layout problems, the untraced numbers, the checks that failed).
 */
export function GraphicsRenderMetrics({
  render,
}: {
  /** A render of the lab, or one attempt of a project's graphic (which has no `repeat_of` but may
   * be another attempt's input drawn again). */
  render: Pick<GraphicRender, "metrics" | "warnings" | "input_call"> & {
    repeat_of?: number | null;
  };
}) {
  const metrics = readMetrics(render.metrics);
  const warnings = warningsOf(render);
  const repeatedOf = (render.repeat_of ?? null) !== null;

  return (
    <Stack gap={4}>
      {metrics !== null && (
        <>
          <Group gap={4}>
            {metrics.checks.map(([key, ok]) => (
              <Badge key={key} size="xs" variant="light" color={ok ? "green" : "red"}>
                {CHECK_LABELS[key]}: {ok ? "ok" : "wrong"}
              </Badge>
            ))}
          </Group>
          <Text size="xs" c="dimmed">
            {[
              metrics.renderSeconds !== null ? `drawn in ${metrics.renderSeconds.toFixed(1)} s` : null,
              metrics.sizeBytes !== null ? formatBytes(metrics.sizeBytes) : null,
              metrics.frames !== null ? `${metrics.frames} frames` : null,
              metrics.voice === null ? null : metrics.voice ? "with the voice" : "no voice",
              metrics.timingSource !== null
                ? `timing ${TIMING_SOURCE_LABELS[metrics.timingSource] ?? metrics.timingSource}`
                : null,
            ]
              .filter((part) => part !== null)
              .join(", ")}
          </Text>
          {(metrics.layoutProblems !== null || metrics.untracedNumbers !== null) && (
            <Text size="xs" c="dimmed">
              {[
                metrics.layoutProblems !== null
                  ? `${metrics.layoutProblems} layout ${metrics.layoutProblems === 1 ? "problem" : "problems"}`
                  : null,
                metrics.untracedNumbers !== null
                  ? `${metrics.untracedNumbers} untraced ${metrics.untracedNumbers === 1 ? "number" : "numbers"}`
                  : null,
              ]
                .filter((part) => part !== null)
                .join(", ")}
            </Text>
          )}
          {metrics.repeat !== null && (
            <Text
              size="xs"
              fw={600}
              c={
                metrics.repeat.kind === "compared" && metrics.repeat.differing === 0
                  ? "green"
                  : "orange"
              }
              data-testid="repeat-result"
            >
              {repeatText(metrics.repeat)}
            </Text>
          )}
        </>
      )}
      {render.input_call !== null ? (
        <Text size="xs" c="dimmed">
          Model call: {callText(render.input_call)}
        </Text>
      ) : (
        repeatedOf && (
          <Text size="xs" c="dimmed">
            No model call: the input is the same as{" "}
            {metrics?.repeat?.ofAttempt != null
              ? `attempt ${metrics.repeat.ofAttempt}`
              : "the render it repeats"}
            .
          </Text>
        )
      )}
      {warnings.map((warning) => (
        <Text key={warning} size="xs" c="orange" style={{ wordBreak: "break-word" }}>
          {warning}
        </Text>
      ))}
    </Stack>
  );
}
