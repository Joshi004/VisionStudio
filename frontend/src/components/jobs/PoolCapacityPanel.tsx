import { Alert, Group, Paper, Progress, SimpleGrid, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJobCapacity } from "../../api/jobs";
import type { ModelCapacity, PoolCapacity } from "../../api/jobs";
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

/** "3 of 4 running, 196 waiting", or "2 running, 5 waiting (no own limit)" when the limit is 0. */
function modelCountsText(model: ModelCapacity): string {
  const counts = countsText(model.running, model.queued);
  if (model.limit === 0) {
    return `${counts} (no own limit)`;
  }
  return model.running > 0
    ? `${model.running} of ${model.limit} running${model.queued > 0 ? `, ${model.queued} waiting` : ""}`
    : `${counts} (limit ${model.limit})`;
}

function PoolCard({ pool }: { pool: PoolCapacity }) {
  // A lower limit never stops a running job, so there can be more jobs running than the limit.
  const percent = pool.limit > 0 ? Math.min(100, (pool.running / pool.limit) * 100) : 0;
  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" align="baseline" wrap="nowrap">
          <Text fw={600}>{pool.label}</Text>
          <Text size="sm" c="dimmed">
            {pool.running} of {pool.limit} jobs running
            {pool.queued > 0 ? `, ${pool.queued} waiting` : ""}
          </Text>
        </Group>
        <Progress
          value={percent}
          color={pool.running >= pool.limit ? "orange" : "blue"}
          aria-label={`${pool.label}: ${pool.running} of ${pool.limit} jobs running`}
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
        {pool.models.length > 0 && (
          <Stack gap={2} mt={4}>
            <Text size="xs" fw={600}>
              Per model
            </Text>
            {pool.models.map((model) => (
              <Group key={model.model} justify="space-between" wrap="nowrap">
                <Text size="xs">{model.label}</Text>
                <Text size="xs" c="dimmed">
                  {modelCountsText(model)}
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
 * The two numbers that limit all work: how many jobs the remote server has at once and how many
 * calls the paid inference API gets at once. Every kind of job shares them, so each pool shows what is using it. The limits are set on the Settings
 * page.
 */
export function PoolCapacityPanel() {
  const { data, isError, error } = useJobCapacity();

  if (isError) {
    return (
      <Alert color="red" title="Could not load the job limits">
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
