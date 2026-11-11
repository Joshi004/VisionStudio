import { Alert, Button, Group, List, Modal, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { usePurgeJobs, type JobPurgeResult } from "../../api/jobs";

type PurgeJobsModalProps = {
  /** The jobs to purge. The modal is open while this is not empty. */
  jobIds: number[];
  /** Called when the modal is closed, after a purge or not. */
  onClose: () => void;
};

function count(results: JobPurgeResult[], outcome: JobPurgeResult["outcome"]): number {
  return results.filter((result) => result.outcome === outcome).length;
}

/**
 * Asks before deleting finished jobs on the GPU server, then shows what happened to each one.
 * Nothing else in the app purges a job by itself: the server cleans up on its own schedule.
 */
export function PurgeJobsModal({ jobIds, onClose }: PurgeJobsModalProps) {
  const purge = usePurgeJobs();
  const results = purge.data;

  function close() {
    purge.reset();
    onClose();
  }

  const problems = results?.filter(
    (result) => result.outcome === "failed" || result.outcome === "skipped",
  );

  return (
    <Modal
      opened={jobIds.length > 0}
      onClose={close}
      title={`Purge ${jobIds.length} ${jobIds.length === 1 ? "job" : "jobs"} on the GPU server?`}
      centered
      closeOnClickOutside={!purge.isPending}
      closeOnEscape={!purge.isPending}
    >
      <Stack gap="md">
        {!results && (
          <Text size="sm">
            This permanently deletes the jobs&apos; output, logs and the uploads no other job
            uses from the GPU server. It cannot be undone. The files and results this app has
            stored are not touched. The server deletes old jobs by itself, so purging is only
            needed to free space or logs earlier.
          </Text>
        )}

        {results && (
          <Stack gap="xs">
            <Text size="sm">
              Purged: {count(results, "purged")}. Already gone from the server:{" "}
              {count(results, "already_gone")}. Skipped: {count(results, "skipped")}. Failed:{" "}
              {count(results, "failed")}.
            </Text>
            {problems && problems.length > 0 && (
              <List size="sm">
                {problems.map((result) => (
                  <List.Item key={result.job_id}>
                    Job {result.job_id}: {result.message}
                  </List.Item>
                ))}
              </List>
            )}
          </Stack>
        )}

        {purge.isError && (
          <Alert color="red" title="The jobs were not purged">
            {describeError(purge.error)}
          </Alert>
        )}

        <Group justify="flex-end">
          {results ? (
            <Button onClick={close}>Close</Button>
          ) : (
            <>
              <Button variant="default" onClick={close} disabled={purge.isPending}>
                Cancel
              </Button>
              <Button color="red" onClick={() => purge.mutate(jobIds)} loading={purge.isPending}>
                Purge
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}
