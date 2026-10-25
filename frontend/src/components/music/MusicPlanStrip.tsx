import { Box, Group, Stack, Text } from "@mantine/core";

import type { MusicPlanCue, MusicPlanTimeline } from "../../api/musicPlan";
import { KIND_COLORS, KIND_LABELS, cueSpan, formatSeconds } from "./musicPlanView";

type MusicPlanStripProps = {
  timeline: MusicPlanTimeline;
  cues: MusicPlanCue[];
};

const LANE_HEIGHT = 18;
const LABEL_WIDTH = 64;

type Block = {
  key: string;
  start: number;
  end: number;
  color: string;
  title: string;
  text?: string;
};

/**
 * A simple time strip of the whole story: the scenes, the narration and dialogue, and the plan's
 * cues in lanes (score, ambience beds, point sounds and hits, silence). Hover a block for what it
 * is. Positions are the nominal seconds of the anchors; exact points come later.
 */
export function MusicPlanStrip({ timeline, cues }: MusicPlanStripProps) {
  const total = Math.max(timeline.total_s, 1);
  const percent = (seconds: number) => `${(Math.min(Math.max(seconds, 0), total) / total) * 100}%`;

  const cueBlocks = (kinds: string[]): Block[] =>
    cues
      .filter((cue) => kinds.includes(cue.kind))
      .map((cue) => {
        const { start, end } = cueSpan(cue);
        return {
          key: cue.id,
          // A point sound or hit is drawn as a thin bar.
          start,
          end: cue.at ? start + total * 0.004 : end,
          color: KIND_COLORS[cue.kind] ?? "gray",
          title: `${cue.id}: ${KIND_LABELS[cue.kind] ?? cue.kind}, ${formatSeconds(start)}${
            cue.at ? "" : ` to ${formatSeconds(end)}`
          }. ${cue.summary}`,
          text: cue.id.replace("cue_", ""),
        };
      });

  const lanes: { label: string; blocks: Block[] }[] = [
    {
      label: "Scenes",
      blocks: timeline.scenes.map((scene, index) => ({
        key: scene.ref,
        start: scene.start_s,
        end: scene.end_s,
        color: index % 2 === 0 ? "gray" : "dark",
        title: `${scene.title} (${scene.mood.start}, then ${scene.mood.middle}, then ${scene.mood.end})`,
        text: scene.title,
      })),
    },
    {
      label: "Speech",
      blocks: timeline.units.map((unit) => ({
        key: unit.ref,
        start: unit.start_s,
        end: unit.end_s,
        color: unit.kind === "narration" ? "grape" : "pink",
        title: `${unit.speaker ?? "Narration"}${unit.off_screen ? " (off screen)" : ""}: ${unit.text}`,
      })),
    },
    { label: "Score", blocks: cueBlocks(["score"]) },
    { label: "Beds", blocks: cueBlocks(["bed"]) },
    { label: "Sounds", blocks: cueBlocks(["point", "hit"]) },
    { label: "Silence", blocks: cueBlocks(["silence"]) },
  ];

  return (
    <Stack gap={2} aria-label="Music plan timeline">
      {lanes.map((lane) => (
        <Group key={lane.label} gap="xs" wrap="nowrap" align="center">
          <Text size="xs" c="dimmed" w={LABEL_WIDTH} style={{ flexShrink: 0 }}>
            {lane.label}
          </Text>
          <Box
            pos="relative"
            h={LANE_HEIGHT}
            style={{
              flex: 1,
              background: "var(--mantine-color-default-hover)",
              borderRadius: 3,
              overflow: "hidden",
            }}
          >
            {lane.blocks.map((block) => (
              <Box
                key={block.key}
                title={block.title}
                pos="absolute"
                top={1}
                bottom={1}
                style={{
                  left: percent(block.start),
                  width: `max(2px, calc(${percent(block.end)} - ${percent(block.start)}))`,
                  background: `var(--mantine-color-${block.color}-6)`,
                  opacity: lane.label === "Speech" ? 0.55 : 0.9,
                  borderRadius: 2,
                  overflow: "hidden",
                  fontSize: 10,
                  lineHeight: `${LANE_HEIGHT - 2}px`,
                  color: "white",
                  paddingLeft: 3,
                  whiteSpace: "nowrap",
                }}
              >
                {block.text}
              </Box>
            ))}
          </Box>
        </Group>
      ))}
      <Group gap="xs" wrap="nowrap">
        <Box w={LABEL_WIDTH} style={{ flexShrink: 0 }} />
        <Group justify="space-between" style={{ flex: 1 }}>
          <Text size="xs" c="dimmed">
            0:00
          </Text>
          <Text size="xs" c="dimmed">
            {formatSeconds(timeline.total_s)}
          </Text>
        </Group>
      </Group>
    </Stack>
  );
}
