import { Alert, Group, Paper, Progress, SimpleGrid, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJobCapacity } from "../../api/jobs";
import type { PoolCapacity } from "../../api/jobs";
import { jobTypeLabel } from "./jobFormat";

/** "2 running, 1 waiting", leaving out the part that is zero. */
function countsText(running: number, queued: number): string {
  const parts: string[] = [];
  if (running > 0) {
    parts.push(`${running} running`);
  }
  if (queued > 0) {
    parts.push(`${queued} waiting`);
  }
  return parts.length === 0 ? "idle" : parts.join(", ");
}

function PoolCard({ pool }: { pool: PoolCapacity }) {
  // A lower limit never stops a running job, so there can be more running than the limit.
  const percent = pool.limit > 0 ? Math.min(100, (pool.running / pool.limit) * 100) : 0;
  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" align="baseline" wrap="nowrap">
          <Text fw={600}>{pool.label}</Text>
          <Text size="sm" c="dimmed">
            {pool.running} of {pool.limit} slots in use
            {pool.queued > 0 ? `, ${pool.queued} waiting` : ""}
          </Text>
        </Group>
        <Progress
          value={percent}
          color={pool.running >= pool.limit ? "orange" : "blue"}
          aria-label={`${pool.label}: ${pool.running} of ${pool.limit} slots in use`}
        />
        {pool.by_type.length === 0 ? (
          <Text size="xs" c="dimmed">
            Nothing is running or waiting.
          </Text>
        ) : (
          <Stack gap={2}>
            {pool.by_type.map((entry) => (
              <Group key={entry.type} justify="space-between" wrap="nowrap">
                <Text size="xs">{jobTypeLabel(entry.type)}</Text>
                <Text size="xs" c="dimmed">
                  {countsText(entry.running, entry.queued)}
                </Text>
              </Group>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

/**
 * The two numbers that limit all work: how many jobs the GPU server runs at once and how many
 * calls the paid inference API gets at once. Every kind of job shares them, so each pool shows
 * what is using it. The limits are set on the Settings page.
 */
export function PoolCapacityPanel() {
  const { data, isError, error } = useJobCapacity();

  if (isError) {
    return (
      <Alert color="red" title="Could not load the GPU and API slots">
        {describeError(error)}
      </Alert>
    );
  }
  if (!data) {
    return null;
  }
  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
      {data.pools.map((pool) => (
        <PoolCard key={pool.pool} pool={pool} />
      ))}
    </SimpleGrid>
  );
}
