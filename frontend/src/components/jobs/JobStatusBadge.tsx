import { Badge, Group, Text } from "@mantine/core";

import type { JobSummary } from "../../api/jobs";
import { showsPhase, stageColor, stageLabel, statusColor } from "./jobFormat";

type BadgeJob = Pick<JobSummary, "status" | "phase"> & {
  /** Missing on the small job models that carry no stage: the badge then shows the status. */
  stage?: JobSummary["stage"];
};

/**
 * The job's stage as a coloured badge (its status when the stage is not known), with the phase
 * next to it while the job is active.
 */
export function JobStatusBadge({ job }: { job: BadgeJob }) {
  const stage = job.stage;
  return (
    <Group gap={6} wrap="nowrap">
      <Badge
        color={stage ? stageColor(stage) : statusColor(job.status)}
        variant="light"
      >
        {stage ? stageLabel(stage) : job.status}
      </Badge>
      {job.phase && showsPhase(job.status) && (
        <Text size="xs" c="dimmed">
          {job.phase}
        </Text>
      )}
    </Group>
  );
}
