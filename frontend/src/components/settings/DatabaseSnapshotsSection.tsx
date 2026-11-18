import { Alert, Button, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import { useDbSnapshots, useMakeDbSnapshot } from "../../api/dbSnapshots";
import { describeError } from "../../api/errors";

const MB = 1024 ** 2;
const GB = 1024 ** 3;

function formatSize(bytes: number): string {
  return bytes >= GB ? `${(bytes / GB).toFixed(2)} GB` : `${Math.round(bytes / MB)} MB`;
}

function formatAge(madeAt: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(madeAt).getTime()) / 60_000));
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours} h ago`;
  }
  return `${Math.round(hours / 24)} days ago`;
}

/** The "Backups" tab of Settings: the database snapshot kept in the files folder (STOR-004). */
export function DatabaseSnapshotsSection() {
  const snapshots = useDbSnapshots();
  const make = useMakeDbSnapshot();
  const data = snapshots.data;

  let last;
  if (snapshots.isError) {
    last = (
      <Text c="red" size="sm">
        {describeError(snapshots.error)}
      </Text>
    );
  } else if (!data) {
    last = <Loader size="sm" />;
  } else if (data.running) {
    last = (
      <Group gap="xs">
        <Loader size="xs" />
        <Text size="sm">Making a snapshot…</Text>
      </Group>
    );
  } else if (data.last) {
    last = (
      <Stack gap={2}>
        <Text fw={500} c={data.stale ? "orange" : "green"}>
          Last snapshot: {new Date(data.last.made_at).toLocaleString()} (
          {formatAge(data.last.made_at)})
        </Text>
        <Text size="xs" c="dimmed">
          {data.last.name}, {formatSize(data.last.size_bytes)}
        </Text>
      </Stack>
    );
  } else if (data.enabled) {
    last = (
      <Text c="orange" fw={500}>
        No snapshot yet.
      </Text>
    );
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={2}>
            <Text fw={600}>Database snapshot</Text>
            <Text size="sm" c="dimmed">
              A compact, checked copy of the database, written to the db-snapshots folder of the
              files folder on this Mac. One is made when the newest is a day old, and only the
              newest is kept. The app keeps working while it is made. Restoring is a manual step
              described in the README.
            </Text>
          </Stack>
          <Button
            onClick={() => make.mutate()}
            loading={make.isPending}
            disabled={!data?.enabled || data.running}
          >
            Make a snapshot now
          </Button>
        </Group>

        {last}

        {data && !data.enabled && data.problem && (
          <Alert color="orange" title="Snapshots are off">
            {data.problem}
          </Alert>
        )}

        {data?.last_error && (
          <Alert color="red" title="The last snapshot failed">
            {data.last_error}
          </Alert>
        )}

        {make.isError && (
          <Text c="red" size="sm">
            {describeError(make.error)}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
