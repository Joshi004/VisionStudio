import { Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";

import { useJobDiagnostics } from "../../api/jobs";
import type { SeriesStats } from "../../api/jobs";

function seconds(value: number): string {
  return `${value.toFixed(value < 10 ? 1 : 0)} s`;
}

/** "median 2.1 s, slowest 10% 5.0 s, worst 9 s", or nothing when there are no samples. */
function secondsText(stats: SeriesStats | undefined): string {
  if (!stats) {
    return "no data yet";
  }
  return `median ${seconds(stats.p50)}, slowest 10% ${seconds(stats.p90)}, worst ${seconds(stats.max)}`;
}

function countText(stats: SeriesStats | undefined): string {
  if (!stats) {
    return "no data yet";
  }
  return `median ${stats.p50}, most ${stats.max}`;
}

type RowProps = { label: string; value: string; hint?: string };

function Row({ label, value, hint }: RowProps) {
  return (
    <Group justify="space-between" align="baseline" wrap="nowrap" gap="md">
      <Text size="xs" title={hint}>
        {label}
      </Text>
      <Text size="xs" c="dimmed" ta="right">
        {value}
      </Text>
    </Group>
  );
}

const POOL_LABELS: Record<string, string> = { gpu: "Remote server", paid_api: "Paid inference API" };

/**
 * Where the time goes between a job being wanted and running: the dispatcher's loop, the story
 * pipeline run's passes, how long jobs wait for a slot, whether the backend is blocked, and the
 * database connections. Numbers are from the last few minutes and start again after a restart.
 */
export function SchedulerHealthPanel() {
  const { data } = useJobDiagnostics();
  if (!data) {
    return null;
  }
  const series = data.series;
  const waitPools = Object.keys(series)
    .filter((name) => name.startsWith("queue_wait_s:"))
    .map((name) => name.slice("queue_wait_s:".length));
  const timeouts = data.counters.pool_timeouts ?? 0;

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="baseline">
          <Text fw={600}>Scheduler health</Text>
          <Text size="xs" c="dimmed">
            last {Math.round(data.window_s / 60)} minutes
          </Text>
        </Group>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
          <Stack gap={4}>
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Dispatcher loop
            </Text>
            <Row
              label="One round"
              value={secondsText(series.tick_s)}
              hint="Every round reads the jobs, checks running ones and starts waiting ones."
            />
            <Row label="Checking running jobs" value={secondsText(series.tick_polls_s)} />
            <Row label="Starting waiting jobs" value={secondsText(series.tick_start_s)} />
            <Row label="Jobs started per round" value={countText(series.tick_started)} />
            <Row
              label="Backend blocked (event loop late)"
              value={secondsText(series.loop_lag_s)}
              hint="How late the backend wakes up. High numbers mean it is busy with one thing."
            />
          </Stack>
          <Stack gap={4}>
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Story pipeline run
            </Text>
            <Row label="Reading what is next" value={secondsText(series.pipeline_evaluate_s)} />
            <Row label="Making the jobs" value={secondsText(series.pipeline_apply_s)} />
            <Row label="Jobs made per pass" value={countText(series.pipeline_made)} />
            <Row
              label="Targets left for the next pass"
              value={countText(series.pipeline_deferred)}
              hint="Ready work that was not queued yet because the pass ran out of time."
            />
          </Stack>
          <Stack gap={4}>
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Wait before a job starts
            </Text>
            {waitPools.length === 0 ? (
              <Text size="xs" c="dimmed">
                no data yet
              </Text>
            ) : (
              waitPools.map((pool) => (
                <Row
                  key={pool}
                  label={POOL_LABELS[pool] ?? pool}
                  value={secondsText(series[`queue_wait_s:${pool}`])}
                />
              ))
            )}
          </Stack>
          <Stack gap={4}>
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Database connections
            </Text>
            <Row
              label="Held at the same time"
              value={countText(series.pool_in_use)}
              hint="The pool allows 15 at most."
            />
            <Row label="Time one is held" value={secondsText(series.pool_hold_s)} />
            <Row
              label="Waited too long for one"
              value={timeouts === 0 ? "never since start" : `${timeouts} times since start`}
            />
          </Stack>
        </SimpleGrid>
      </Stack>
    </Paper>
  );
}
