import { Badge, Group, Paper, Stack, Text, Title } from "@mantine/core";

import { STORY_STAGES } from "./storyStages";

/**
 * The pipeline's stages, in order. A stage is a placeholder until its phase is built; one that
 * can be run is marked "Available" and has its own panel above this list.
 */
export function StageList() {
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Pipeline</Title>
        {STORY_STAGES.map((stage, index) => (
          <Group key={stage.id} justify="space-between" align="flex-start" wrap="nowrap">
            <Stack gap={0}>
              <Text fw={500}>
                {index + 1}. {stage.name}
              </Text>
              <Text size="sm" c="dimmed">
                {stage.description}
              </Text>
            </Stack>
            <Badge
              color={stage.available ? "green" : "gray"}
              variant="light"
              style={{ flexShrink: 0 }}
            >
              {stage.available ? "Available" : "Not available yet"}
            </Badge>
          </Group>
        ))}
      </Stack>
    </Paper>
  );
}
