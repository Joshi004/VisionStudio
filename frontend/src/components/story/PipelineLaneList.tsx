import { Anchor, Badge, Group, Stack, Text } from "@mantine/core";

import type { PipelineLane } from "../../api/storyPipeline";
import { useProjectPanels } from "./projectPanels";

const LANE_STATUS: Record<
  PipelineLane["status"],
  { label: string; color: string }
> = {
  waiting: { label: "Waiting", color: "gray" },
  going: { label: "Going", color: "blue" },
  review: { label: "Your review", color: "yellow" },
  problem: { label: "Problem", color: "red" },
  done: { label: "Done", color: "green" },
};

/** The panel that holds the scene's own buttons, with its newest scene render. */
const SCENE_PANEL = "shot_generation";

type PipelineLaneListProps = {
  lanes: PipelineLane[];
};

/** What a scene is doing now, in a few words. */
function laneText(lane: PipelineLane): string {
  if (lane.status === "done") {
    return "Every step is complete";
  }
  if (lane.status === "review") {
    return lane.review_label ?? "Waiting for your review";
  }
  return lane.step_label ?? "";
}

/**
 * Where every scene stands in a run (SCN-010): each scene moves through the per-scene steps on
 * its own, so early scenes are ready while later scenes are still being made. "Show" opens the
 * panel with the scene's buttons and its newest scene render.
 */
export function PipelineLaneList({ lanes }: PipelineLaneListProps) {
  const { openPanel } = useProjectPanels();

  function show() {
    openPanel(SCENE_PANEL);
    // The panel is rendered by the next frame, so the scroll lands on its final position.
    requestAnimationFrame(() =>
      document
        .getElementById(`pipeline-step-${SCENE_PANEL}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }

  if (lanes.length === 0) {
    return null;
  }

  return (
    <Stack gap={2}>
      <Text size="sm" fw={600}>
        Scenes
      </Text>
      {lanes.map((lane) => {
        const status = LANE_STATUS[lane.status];
        return (
          <Group key={lane.scene_id} gap="xs" wrap="nowrap">
            <Badge
              variant="light"
              color={status.color}
              size="sm"
              w={92}
              style={{ flexShrink: 0 }}
            >
              {status.label}
            </Badge>
            <Text size="sm">
              {lane.index !== null ? `Scene ${lane.index}: ` : ""}
              {lane.title}
            </Text>
            <Text size="xs" c="dimmed">
              {laneText(lane)}
              {lane.status === "done" ? "" : `, ${lane.done} of ${lane.total}`}
            </Text>
            <Anchor component="button" type="button" size="xs" onClick={show}>
              Show
            </Anchor>
          </Group>
        );
      })}
    </Stack>
  );
}
