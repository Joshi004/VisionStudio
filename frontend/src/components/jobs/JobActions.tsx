import { Button, Group, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useCancelJob, useResubmitJob, type JobSummary } from "../../api/jobs";

/**
 * Cancel (a job that has not started, or one the GPU server does not know) and Resubmit
 * (a job the GPU server does not know). It shows nothing when neither applies.
 */
export function JobActions({ job }: { job: Pick<JobSummary, "id" | "can_cancel" | "can_resubmit"> }) {
  const cancel = useCancelJob();
  const resubmit = useResubmitJob();

  if (!job.can_cancel && !job.can_resubmit) {
    return null;
  }

  const failure = cancel.isError ? cancel.error : resubmit.isError ? resubmit.error : null;

  return (
    <Stack gap={4} align="flex-start">
      <Group gap="xs">
        {job.can_resubmit && (
          <Button
            size="compact-xs"
            variant="light"
            loading={resubmit.isPending}
            onClick={(event) => {
              event.stopPropagation();
              resubmit.mutate(job.id);
            }}
          >
            Resubmit
          </Button>
        )}
        {job.can_cancel && (
          <Button
            size="compact-xs"
            variant="subtle"
            color="red"
            loading={cancel.isPending}
            onClick={(event) => {
              event.stopPropagation();
              cancel.mutate(job.id);
            }}
          >
            Cancel
          </Button>
        )}
      </Group>
      {failure && (
        <Text size="xs" c="red">
          {describeError(failure)}
        </Text>
      )}
    </Stack>
  );
}
