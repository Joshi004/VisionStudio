import { Alert, Badge, Button, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useGraphicsRuns } from "../../api/graphicsLab";
import { DeleteLabSampleButton } from "../lab/DeleteLabSampleButton";
import { ORIENTATION_LABELS, snippet, stateText } from "./graphicsLabView";

/**
 * The runs, newest first. A run stays until it is deleted. Each shows its line, its orientation
 * and what it is doing in words.
 */
export function GraphicsRunList({ onOpen }: { onOpen: (runId: number) => void }) {
  const runs = useGraphicsRuns();
  const all = runs.data?.pages.flat() ?? [];

  return (
    <Stack gap="sm">
      <Text size="sm" fw={600}>
        Runs
      </Text>
      {runs.isLoading && <Loader size="sm" />}
      {runs.isError && (
        <Alert color="red" title="Could not load the runs">
          {describeError(runs.error)}
        </Alert>
      )}
      {runs.data && all.length === 0 && (
        <Text size="sm" c="dimmed">
          No runs yet. The runs you make appear here, and stay until you delete them.
        </Text>
      )}

      {all.map((run) => (
        <Paper key={run.id} withBorder p="sm" radius="md">
          <Stack gap="xs">
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Text size="sm" style={{ wordBreak: "break-word" }}>
                {snippet(run.line_text)}
              </Text>
              <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
                <Badge variant="light" color="gray">
                  Run {run.id}
                </Badge>
                <Badge variant="outline">{ORIENTATION_LABELS[run.orientation]}</Badge>
              </Group>
            </Group>
            <Group justify="space-between">
              <Text size="xs" c="dimmed">
                {stateText(run.state)} · {new Date(run.created_at).toLocaleString()}
              </Text>
              <Group gap="xs">
                <Button size="compact-xs" variant="subtle" onClick={() => onOpen(run.id)}>
                  Open
                </Button>
                <DeleteLabSampleButton kind="graphic_run" sampleId={run.id} />
              </Group>
            </Group>
          </Stack>
        </Paper>
      ))}

      {runs.hasNextPage && (
        <Group>
          <Button variant="default" onClick={() => runs.fetchNextPage()} loading={runs.isFetchingNextPage}>
            Show older runs
          </Button>
        </Group>
      )}
    </Stack>
  );
}
