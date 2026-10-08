import type { ReactNode } from "react";
import { Alert, Anchor, Code, Drawer, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import { useJob, type JobDetail } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import { formatDateTime } from "../../format";
import { useNow } from "../../hooks/useNow";
import { elapsedText, jobTypeLabel } from "./jobFormat";
import { JobActions } from "./JobActions";
import { JobStatusBadge } from "./JobStatusBadge";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Group gap="xs" align="flex-start" wrap="nowrap">
      <Text size="sm" c="dimmed" w={130} style={{ flexShrink: 0 }}>
        {label}
      </Text>
      <Text size="sm" style={{ wordBreak: "break-word" }}>
        {children}
      </Text>
    </Group>
  );
}

function when(iso: string | null | undefined): string {
  return iso ? formatDateTime(iso) : "—";
}

function Json({ title, value }: { title: string; value: unknown }) {
  return (
    <Stack gap={4}>
      <Title order={5}>{title}</Title>
      {value === null || value === undefined ? (
        <Text size="sm" c="dimmed">
          Nothing yet.
        </Text>
      ) : (
        <Code block style={{ maxHeight: 320, overflow: "auto" }}>
          {JSON.stringify(value, null, 2)}
        </Code>
      )}
    </Stack>
  );
}

function JobDetails({ job, now }: { job: JobDetail; now: number }) {
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start">
        <JobStatusBadge job={job} />
        <JobActions job={job} />
      </Group>
      <Field label="Type">{jobTypeLabel(job.type)}</Field>
      <Field label="Project">
        <Anchor component={Link} to={`/projects/${job.project_id}`}>
          {job.project_name}
        </Anchor>
      </Field>
      <Field label="Scene">{job.scene_index === null ? "—" : `Scene ${job.scene_index + 1}`}</Field>
      <Field label="Phase">{job.phase ?? "—"}</Field>
      <Field label="Attempt">{job.attempt}</Field>
      <Field label="Time">{elapsedText(job, now) || "—"}</Field>
      <Field label="Created">{when(job.created_at)}</Field>
      <Field label="Started">{when(job.started_at)}</Field>
      <Field label="Last checked">{when(job.last_checked_at)}</Field>
      <Field label="Finished">{when(job.finished_at)}</Field>
      <Field label="Provider">{job.provider}</Field>
      <Field label="Server job id">{job.provider_job_id ?? "—"}</Field>

      {job.error && (
        <Alert color="red" title="Error">
          <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {job.error}
          </Text>
        </Alert>
      )}

      <Json title="Input" value={job.input} />
      <Json title="Output" value={job.output} />
    </Stack>
  );
}

/** The whole job on the right of the page: its times, its error, and its input and output JSON. */
export function JobDetailDrawer({ jobId, onClose }: { jobId: number | null; onClose: () => void }) {
  const { data: job, isLoading, isError, error, dataUpdatedAt } = useJob(jobId);
  // The clock ticks once a second while the job is waiting or running.
  const now = useNow(isJobActive(job), dataUpdatedAt);

  return (
    <Drawer
      opened={jobId !== null}
      onClose={onClose}
      position="right"
      size="lg"
      title={jobId === null ? "Job" : `Job ${jobId}`}
    >
      {isLoading && <Loader size="sm" />}
      {isError && (
        <Alert color="red" title="Could not load the job">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}
      {job && jobId !== null && job.id === jobId && <JobDetails job={job} now={now} />}
    </Drawer>
  );
}
