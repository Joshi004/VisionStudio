import { Alert, Badge, Button, Loader, Stack, Table, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useLabRuns } from "../../api/imageLab";
import { formatDateTime } from "../../format";
import { MODE_LABELS } from "./labView";

/**
 * Every run, newest first, so results can be compared later. A run opens in a drawer. Reads
 * the database only, and refreshes after a run, on returning to the tab and on Refresh.
 */
export function LabHistory({ onOpen }: { onOpen: (runId: number) => void }) {
  const runs = useLabRuns();
  const rows = runs.data?.pages.flatMap((page) => page.runs) ?? [];

  return (
    <Stack gap="sm">
      <Title order={4}>History</Title>
      {runs.isLoading && <Loader size="sm" />}
      {runs.isError && (
        <Alert color="red" title="Could not load the history">
          {describeError(runs.error)} Press Refresh to try again.
        </Alert>
      )}
      {runs.data && rows.length === 0 && <Text c="dimmed">No runs yet.</Text>}
      {rows.length > 0 && (
        <Table verticalSpacing="xs" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Result</Table.Th>
              <Table.Th>Run</Table.Th>
              <Table.Th>Mode</Table.Th>
              <Table.Th>Prompt</Table.Th>
              <Table.Th>Size</Table.Th>
              <Table.Th>Time</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((run) => {
              const first = run.images[0];
              return (
                <Table.Tr key={run.id}>
                  <Table.Td style={{ width: 64 }}>
                    {first ? (
                      <img
                        src={first.url}
                        alt={`Run ${run.id}`}
                        loading="lazy"
                        style={{ width: 48, height: 64, objectFit: "cover", borderRadius: 4 }}
                      />
                    ) : (
                      <Text size="xs" c="dimmed">
                        none
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{run.id}</Text>
                    <Text size="xs" c="dimmed">
                      {formatDateTime(run.created_at)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{MODE_LABELS[run.mode]}</Text>
                    {run.references.length > 0 && (
                      <Text size="xs" c="dimmed">
                        {run.references.length} {run.references.length === 1 ? "reference" : "references"}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td style={{ maxWidth: 360 }}>
                    <Text size="sm" lineClamp={2}>
                      {run.prompt}
                    </Text>
                  </Table.Td>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>
                    <Text size="sm">{typeof run.params.size === "string" ? run.params.size : ""}</Text>
                  </Table.Td>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>
                    <Text size="sm">{run.seconds !== null ? `${run.seconds.toFixed(1)} s` : ""}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={run.status === "succeeded" ? "green" : "red"} variant="light">
                      {run.status}
                    </Badge>
                    {run.http_status !== null && run.status === "failed" && (
                      <Text size="xs" c="dimmed">
                        HTTP {run.http_status}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Button size="compact-xs" variant="default" onClick={() => onOpen(run.id)}>
                      Open
                    </Button>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      )}
      {runs.hasNextPage && (
        <Button
          variant="default"
          size="xs"
          loading={runs.isFetchingNextPage}
          onClick={() => void runs.fetchNextPage()}
          style={{ alignSelf: "flex-start" }}
        >
          Show older runs
        </Button>
      )}
    </Stack>
  );
}
