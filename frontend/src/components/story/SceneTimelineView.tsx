import { Box, Group, Stack, Text } from "@mantine/core";

import type { SceneTimeline } from "../../api/shotPlans";

type SceneTimelineViewProps = {
  timeline: SceneTimeline;
  /** Where the scene starts in the whole story, when it is known. */
  storyStartSeconds: number | null;
};

const BAR_HEIGHT = 26;

function seconds(value: number): string {
  return `${value.toFixed(2)} s`;
}

/** What a cut shot's clip is: its H3 length, and how much of its end the render trims. */
function clipNote(frames: number | null | undefined, shotSeconds: number): string {
  if (frames == null) {
    return "";
  }
  const trimmed = Math.max(0, frames / 24 - shotSeconds);
  return `. Clip of ${frames} frames (${seconds(frames / 24)}), the last ${seconds(trimmed)} trimmed.`;
}

function percent(value: number, total: number): string {
  return `${(total > 0 ? (value / total) * 100 : 0).toFixed(3)}%`;
}

/** Marks on the scale: every second for a short scene, else every 5 s. */
function tickSeconds(total: number): number[] {
  const step = total <= 20 ? 1 : 5;
  const ticks: number[] = [];
  for (let at = 0; at <= total; at += step) {
    ticks.push(at);
  }
  return ticks;
}

type BarProps = {
  start: number;
  end: number;
  total: number;
  label: string;
  title: string;
  color: string;
  outline?: boolean;
};

function Bar({ start, end, total, label, title, color, outline }: BarProps) {
  return (
    <Box
      title={title}
      style={{
        position: "absolute",
        top: 0,
        height: BAR_HEIGHT,
        left: percent(start, total),
        width: percent(end - start, total),
        boxSizing: "border-box",
        overflow: "hidden",
        whiteSpace: "nowrap",
        padding: "0 4px",
        borderRadius: 4,
        border: `${outline ? 2 : 1}px solid var(--mantine-color-${color}-${outline ? 7 : 4})`,
        background: `var(--mantine-color-${color}-light)`,
      }}
    >
      <Text size="xs" lh={`${BAR_HEIGHT - 4}px`} truncate>
        {label}
      </Text>
    </Box>
  );
}

/**
 * One scene's exact timeline (`Path_ahead.md` Sections 22 to 24), read only: the shots as bars
 * along the scene, the speech units placed where they are heard, and the problems found. A
 * speech unit that starts later than its shot (the unit before it is still playing) has a
 * heavier outline.
 */
export function SceneTimelineView({
  timeline,
  storyStartSeconds,
}: SceneTimelineViewProps) {
  const total = timeline.total_seconds;
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        {seconds(total)} in the scene
        {storyStartSeconds !== null &&
          `, starting at ${seconds(storyStartSeconds)} in the story`}
      </Text>

      <Box>
        <Text size="xs" c="dimmed" mb={2}>
          Shots
        </Text>
        <Box pos="relative" h={BAR_HEIGHT}>
          {timeline.shots.map((shot) => (
            <Bar
              key={shot.shot_id}
              start={shot.start_seconds}
              end={shot.end_seconds}
              total={total}
              label={`${shot.shot_id} \u00B7 ${seconds(shot.end_seconds - shot.start_seconds)}`}
              title={`${shot.shot_id}: ${seconds(shot.start_seconds)} to ${seconds(shot.end_seconds)}${clipNote(shot.clip_frames, shot.end_seconds - shot.start_seconds)}`}
              color={
                timeline.problems.some(
                  (problem) =>
                    problem.shot_id === shot.shot_id &&
                    problem.severity === "blocking",
                )
                  ? "red"
                  : timeline.problems.some(
                        (problem) => problem.shot_id === shot.shot_id,
                      )
                    ? "yellow"
                    : "gray"
              }
            />
          ))}
        </Box>
      </Box>

      <Box>
        <Text size="xs" c="dimmed" mb={2}>
          Speech
        </Text>
        <Box pos="relative" h={BAR_HEIGHT}>
          {timeline.units.map((unit) => (
            <Bar
              key={unit.unit_id}
              start={unit.start_seconds}
              end={unit.end_seconds}
              total={total}
              label={unit.unit_id}
              title={`${unit.unit_id} (${unit.kind}): ${seconds(unit.start_seconds)} to ${seconds(unit.end_seconds)}, in ${unit.shot_ids.join(", ")}${unit.delayed ? ". Starts later than its shot: the speech before it is still playing." : ""}`}
              color={unit.kind === "narration" ? "blue" : "teal"}
              outline={unit.delayed}
            />
          ))}
        </Box>
      </Box>

      <Box pos="relative" h={14} aria-hidden>
        {tickSeconds(total).map((at) => (
          <Text
            key={at}
            size="10px"
            c="dimmed"
            pos="absolute"
            left={percent(at, total)}
            style={{ transform: "translateX(-50%)" }}
          >
            {at}
          </Text>
        ))}
      </Box>

      {timeline.problems.length > 0 && (
        <Stack gap={2}>
          {timeline.problems.map((problem) => (
            <Group
              key={`${problem.code}-${problem.shot_id}-${problem.unit_id}`}
              gap={6}
              wrap="nowrap"
              align="flex-start"
            >
              <Text
                size="xs"
                fw={600}
                c={problem.severity === "blocking" ? "red.8" : "yellow.8"}
                style={{ flexShrink: 0 }}
              >
                {problem.severity === "blocking" ? "Blocking" : "Warning"}
              </Text>
              <Text size="xs">{problem.message}</Text>
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
