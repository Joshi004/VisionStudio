import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useGraphicsRun } from "../../api/graphicsLab";
import { DeleteLabSampleButton } from "../lab/DeleteLabSampleButton";
import { GraphicsEngineCard } from "./GraphicsEngineCard";
import { ORIENTATION_LABELS, stateText } from "./graphicsLabView";

/**
 * One run: its line, the brief area (empty until the director call exists) and the four engine
 * cards. A landscape run shows the cards two by two, a portrait run in four columns.
 */
export function GraphicsRunPage({ runId, onBack }: { runId: number; onBack: () => void }) {
  const run = useGraphicsRun(runId);
  const data = run.data;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Button variant="subtle" size="compact-sm" onClick={onBack}>
          ← All runs
        </Button>
        {data && <DeleteLabSampleButton kind="graphic_run" sampleId={data.id} onDeleted={onBack} />}
      </Group>

      {run.isLoading && <Loader size="sm" />}
      {run.isError && (
        <Alert color="red" title="Could not load the run">
          {describeError(run.error)}
        </Alert>
      )}

      {data && (
        <>
          <Group gap="xs">
            <Title order={4}>Run {data.id}</Title>
            <Badge variant="outline">{ORIENTATION_LABELS[data.orientation]}</Badge>
            <Text size="xs" c="dimmed">
              {data.width} x {data.height}, {data.fps} frames a second
            </Text>
          </Group>

          <Paper withBorder p="md" radius="md">
            <Stack gap={4}>
              <Text size="xs" fw={600} c="dimmed">
                The line
              </Text>
              <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {data.line_text}
              </Text>
            </Stack>
          </Paper>

          <Paper withBorder p="md" radius="md">
            <Stack gap={4}>
              <Text size="xs" fw={600} c="dimmed">
                Brief
              </Text>
              <Text size="sm" c="dimmed">
                {stateText(data.state)}.
              </Text>
              {data.last_error !== null && (
                <Text size="sm" c="red" style={{ wordBreak: "break-word" }}>
                  {data.last_error}
                </Text>
              )}
            </Stack>
          </Paper>

          <SimpleGrid cols={data.orientation === "portrait" ? { base: 2, md: 4 } : { base: 1, sm: 2 }}>
            {data.engines.map((engine) => (
              <GraphicsEngineCard key={engine.key} engine={engine} width={data.width} height={data.height} />
            ))}
          </SimpleGrid>
        </>
      )}
    </Stack>
  );
}
