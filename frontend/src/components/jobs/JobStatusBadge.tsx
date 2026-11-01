import { Badge, Group, Progress, Stack, Text, Tooltip } from "@mantine/core";

import type { JobSummary } from "../../api/jobs";
import { formatBytes, formatTime } from "../../format";
import { showsPhase, stageColor, stageLabel, statusColor } from "./jobFormat";

type BadgeJob = Pick<JobSummary, "status" | "phase"> & {
  /** Missing on the small job models that carry no stage: the badge then shows the status. */
  stage?: JobSummary["stage"];
  /** Missing on the small job models: no upload line and no info mark are shown. */
  upload?: JobSummary["upload"];
  connection?: JobSummary["connection"];
  last_checked_at?: JobSummary["last_checked_at"];
};

type Connection = NonNullable<JobSummary["connection"]>;

/**
 * An info mark for a job whose GPU server does not answer. The badge next to it still shows the
 * last thing the server told, so the hover says since when the server has not answered, and when
 * that status was last confirmed.
 */
function NotAnsweringMark({
  connection,
  lastChecked,
}: {
  connection: Connection;
  lastChecked: string | null | undefined;
}) {
  const confirmed = lastChecked ? formatTime(lastChecked) : "not yet";
  const label =
    `GPU server not answering since ${formatTime(connection.since)} ` +
    `(last try ${formatTime(connection.last_failed_at)}). ${connection.message} ` +
    `This status was last confirmed by the server at ${confirmed}.`;
  return (
    <Tooltip label={label} withArrow multiline w={320}>
      <Text
        component="span"
        size="sm"
        c="orange"
        fw={700}
        aria-label="The GPU server is not answering"
        style={{ cursor: "help" }}
      >
        ⓘ
      </Text>
    </Tooltip>
  );
}

function filesSentText(filesDone: number): string {
  return `${filesDone} ${filesDone === 1 ? "file" : "files"} sent`;
}

/**
 * "lab-frame-12.png: 18.4 MB of 42.0 MB (44%), 2 files sent", with a bar. While the job waits
 * for an upload place, the file it holds is the one it already sent, so only the count is shown.
 */
function UploadLine({
  upload,
  waiting,
}: {
  upload: NonNullable<JobSummary["upload"]>;
  waiting: boolean;
}) {
  if (waiting) {
    if (upload.files_done === 0) {
      return null;
    }
    return (
      <Text size="xs" c="dimmed">
        {filesSentText(upload.files_done)}, waiting for a free upload place
      </Text>
    );
  }
  const percent =
    upload.total_bytes > 0
      ? Math.min(100, Math.floor((upload.sent_bytes / upload.total_bytes) * 100))
      : 0;
  const filesText = upload.files_done === 0 ? "" : `, ${filesSentText(upload.files_done)}`;
  return (
    <Tooltip
      label="Bytes handed to the connection. Through the tunnel the last few MB can still be on their way when the bar is full."
      withArrow
      multiline
      w={300}
    >
      <Stack gap={2} maw={320}>
        <Progress value={percent} size="sm" />
        <Text size="xs" c="dimmed">
          {upload.filename}: {formatBytes(upload.sent_bytes)} of {formatBytes(upload.total_bytes)} (
          {percent}%){filesText}
        </Text>
      </Stack>
    </Tooltip>
  );
}

/**
 * The job's stage as a coloured badge (its status when the stage is not known), with the phase
 * next to it while the job is active. An info mark follows when the GPU server does not answer
 * (the badge is then the last known state), and an upload in progress shows its bar below.
 */
export function JobStatusBadge({ job }: { job: BadgeJob }) {
  const stage = job.stage;
  const row = (
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
      {job.connection && (
        <NotAnsweringMark connection={job.connection} lastChecked={job.last_checked_at} />
      )}
    </Group>
  );

  if (!job.upload) {
    return row;
  }
  return (
    <Stack gap={4}>
      {row}
      <UploadLine upload={job.upload} waiting={stage === "waiting_to_upload"} />
    </Stack>
  );
}
