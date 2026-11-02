import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useGraphicsRun } from "../../api/graphicsLab";
import { DeleteLabSampleButton } from "../lab/DeleteLabSampleButton";
import { GraphicsBriefPanel } from "./GraphicsBriefPanel";
import { GraphicsEngineCard } from "./GraphicsEngineCard";
import { ORIENTATION_LABELS } from "./graphicsLabView";

type GraphicsRunPageProps = {
  runId: number;
  onBack: () => void;
  /** Opens another run (Ask again makes one). */
  onOpenRun: (id: number) => void;
};

/**
 * One run: its line, its brief (GFX-003) and the four engine cards. A landscape run shows the
 * cards two by two, a portrait run in four columns.
 */
export function GraphicsRunPage({ runId, onBack, onOpenRun }: GraphicsRunPageProps) {
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

          <GraphicsBriefPanel run={data} onOpenRun={onOpenRun} />

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
