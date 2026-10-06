import { Button, Group, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useGpuConnection, useTestGpuConnection, type ConnectionTest } from "../../api/gpu";

function Outcome({ result }: { result: ConnectionTest }) {
  return (
    <Stack gap={2}>
      {result.reachable ? (
        <Text c="green" fw={500}>
          Reachable in {result.elapsed_ms} ms
          {result.default_partition ? ` · default partition ${result.default_partition}` : ""}
        </Text>
      ) : (
        <Text c="red" fw={500}>
          Unreachable: {result.error ?? "no reason given"}
        </Text>
      )}
      <Text size="xs" c="dimmed">
        Called {result.called_url} at {new Date(result.checked_at).toLocaleString()}
      </Text>
    </Stack>
  );
}

export function GpuConnectionTest() {
  const connection = useGpuConnection();
  const test = useTestGpuConnection();

  let status;
  if (connection.isError) {
    status = (
      <Text c="red" size="sm">
        Could not load the last test result: {describeError(connection.error)}
      </Text>
    );
  } else if (connection.isLoading) {
    status = (
      <Text c="dimmed" size="sm">
        Loading the last test result…
      </Text>
    );
  } else if (connection.data?.last_test) {
    status = <Outcome result={connection.data.last_test} />;
  } else {
    status = (
      <Text c="dimmed" size="sm">
        Not tested yet for this address.
      </Text>
    );
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={600}>GPU server connection</Text>
            <Text size="sm" c="dimmed">
              Tests the saved GPU server URL by calling its health endpoint. Nothing else in the
              app calls the server while a page loads.
            </Text>
          </Stack>
          <Button onClick={() => test.mutate()} loading={test.isPending}>
            Test connection
          </Button>
        </Group>

        {status}

        {test.isError && (
          <Text c="red" size="sm">
            Could not run the test: {describeError(test.error)}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
