import { Box, Group, Stack, Text } from "@mantine/core";

import type {
  MusicPlacementContent,
  PlacedSound,
} from "../../api/musicPlacement";
import {
  JOIN_LABELS,
  KIND_COLORS,
  KIND_LABELS,
  formatSeconds,
} from "./musicPlanView";

type MusicPlacementStripProps = {
  content: MusicPlacementContent;
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
  // The share of the block (0 to 1) that is a fade at its start and at its end.
  fadeIn?: number;
  fadeOut?: number;
  opacity?: number;
};

function seconds(sample: number, rate: number): number {
  return sample / rate;
}

/** The block's colour, with its fades drawn as a ramp from nothing to full. */
function background(block: Block): string {
  const color = `var(--mantine-color-${block.color}-6)`;
  const fadeIn = Math.min(Math.max(block.fadeIn ?? 0, 0), 1) * 100;
  const fadeOut = Math.min(Math.max(block.fadeOut ?? 0, 0), 1) * 100;
  if (fadeIn === 0 && fadeOut === 0) return color;
  return `linear-gradient(to right, transparent 0%, ${color} ${fadeIn}%, ${color} ${
    100 - fadeOut
  }%, transparent 100%)`;
}

function placementBlock(item: PlacedSound, rate: number): Block {
  const start = seconds(item.story_start_sample, rate);
  const length = seconds(item.length_samples, rate);
  const share = (samples: number) =>
    item.length_samples > 0 ? samples / item.length_samples : 0;
  const flagged = item.start?.flagged || item.end?.flagged;
  return {
    key: item.item_id,
    start,
    end: start + Math.max(length, 0.05),
    color: flagged ? "red" : (KIND_COLORS[item.kind] ?? "gray"),
    title: `${item.item_id}: ${KIND_LABELS[item.kind] ?? item.kind}, ${start.toFixed(2)} s to ${(
      start + length
    ).toFixed(2)} s. ${item.summary}`,
    text: item.cue_id.replace("cue_", ""),
    fadeIn: share(item.fade_in.samples),
    fadeOut: share(item.fade_out.samples),
  };
}

/**
 * The placed music against the story it was placed on: the scenes, the speech and the shot cuts,
 * then the score, the ambience beds and the sounds at their exact seconds. A fade is drawn as a
 * ramp at the end of a block, a join as a marker, and a point that could not be placed well in
 * red. Hover anything for what it is.
 */
export function MusicPlacementStrip({ content }: MusicPlacementStripProps) {
  const { timeline, placements, joins, flags } = content;
  const rate = content.sample_rate;
  const total = Math.max(timeline.total_s, 1);
  const percent = (value: number) =>
    `${(Math.min(Math.max(value, 0), total) / total) * 100}%`;

  const ofLane = (lane: string) =>
    placements
      .filter((item) => item.lane === lane)
      .map((item) => placementBlock(item, rate));

  const lanes: { label: string; blocks: Block[] }[] = [
    {
      label: "Scenes",
      blocks: timeline.scenes.map((scene, index) => ({
        key: scene.ref,
        start: scene.start_s,
        end: scene.end_s,
        color: index % 2 === 0 ? "gray" : "dark",
        title: scene.title,
        text: scene.title,
      })),
    },
    {
      label: "Speech",
      blocks: timeline.speech.map((unit) => ({
        key: unit.ref,
        start: unit.start_s,
        end: unit.end_s,
        color: unit.kind === "narration" ? "grape" : "pink",
        title: `${unit.kind === "narration" ? "Narration" : "Dialogue"} ${unit.ref}`,
        opacity: 0.55,
      })),
    },
    {
      label: "Cuts",
      blocks: timeline.cuts_s.map((cut) => ({
        key: `cut-${cut}`,
        start: cut,
        end: cut + total * 0.002,
        color: "gray",
        title: `Shot cut at ${cut.toFixed(2)} s`,
      })),
    },
    { label: "Score", blocks: ofLane("score") },
    { label: "Beds", blocks: ofLane("bed") },
    { label: "Sounds", blocks: ofLane("sounds") },
    {
      label: "Joins",
      blocks: joins.map((join) => ({
        key: `${join.from_cue}-${join.to_cue}`,
        start: join.point_s - join.length_s / 2,
        end: join.point_s + join.length_s / 2,
        color: "indigo",
        title: `${JOIN_LABELS[join.type] ?? join.type} from ${join.from_cue} to ${join.to_cue} at ${join.point_s.toFixed(
          2,
        )} s, ${join.length_s.toFixed(2)} s long${
          join.made_as !== join.type
            ? ` (made as ${JOIN_LABELS[join.made_as] ?? join.made_as})`
            : ""
        }`,
      })),
    },
    {
      label: "Flags",
      blocks: flags.map((flag, index) => ({
        key: `flag-${index}`,
        start: flag.second,
        end: flag.second + total * 0.003,
        color: "red",
        title: flag.message,
      })),
    },
  ];

  return (
    <Stack gap={2} aria-label="Music placement timeline">
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
                  background: background(block),
                  opacity: block.opacity ?? 0.9,
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
