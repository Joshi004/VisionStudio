import { Badge, Group, Text } from "@mantine/core";

import type { JobSummary } from "../../api/jobs";
import { showsPhase, statusColor } from "./jobFormat";

/** The status as a coloured badge, with the phase next to it while the job is active. */
export function JobStatusBadge({ job }: { job: Pick<JobSummary, "status" | "phase"> }) {
  return (
    <Group gap={6} wrap="nowrap">
      <Badge color={statusColor(job.status)} variant="light">
        {job.status}
      </Badge>
      {job.phase && showsPhase(job.status) && (
        <Text size="xs" c="dimmed">
          {job.phase}
        </Text>
      )}
    </Group>
  );
}
