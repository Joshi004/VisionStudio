import { Badge, Box, Group, Paper, Stack, Text } from "@mantine/core";

import type { GraphicEngine } from "../../api/graphicsLab";
import { GraphicsRenderVerdict } from "./GraphicsRenderVerdict";

type GraphicsEngineCardProps = {
  engine: GraphicEngine;
  /** The size of every video of the run, so the empty frame has the video's shape. */
  width: number;
  height: number;
};

/**
 * One of the four engines of a run. For now every card says "not built yet": an engine is built
 * by its own phase, and its card then shows the newest video and the verdict. The full
 * comparison (the four videos played together) is a later phase.
 */
export function GraphicsEngineCard({ engine, width, height }: GraphicsEngineCardProps) {
  // The renders are newest first.
  const newest = engine.renders[0];

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group justify="space-between" gap="xs">
          <Text size="sm" fw={600}>
            {engine.label}
          </Text>
          {!engine.built && (
            <Badge variant="light" color="gray">
              Not built yet
            </Badge>
          )}
        </Group>

        {newest?.url ? (
          <video
            controls
            preload="metadata"
            src={newest.url}
            style={{ width: "100%", aspectRatio: `${width} / ${height}`, background: "black" }}
          />
        ) : (
          <Box
            style={{
              aspectRatio: `${width} / ${height}`,
              border: "1px dashed var(--mantine-color-gray-5)",
              borderRadius: "var(--mantine-radius-sm)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Text size="xs" c="dimmed" ta="center" px="xs">
              {engine.built ? "No video yet" : "Not built yet"}
            </Text>
          </Box>
        )}

        {newest && (
          <>
            <Text size="xs" c="dimmed">
              Attempt {newest.attempt}
              {engine.renders.length > 1 ? ` of ${engine.renders.length}` : ""}
            </Text>
            {newest.last_error !== null && (
              <Text size="xs" c="red" style={{ wordBreak: "break-word" }}>
                {newest.last_error}
              </Text>
            )}
            <GraphicsRenderVerdict key={newest.id} render={newest} />
          </>
        )}
      </Stack>
    </Paper>
  );
}
