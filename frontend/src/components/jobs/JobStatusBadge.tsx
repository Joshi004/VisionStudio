import { Badge, Group, Progress, Stack, Text, Tooltip } from "@mantine/core";

import type { JobSummary } from "../../api/jobs";
import { formatBytes, formatTime } from "../../format";
import { showsPhase, stageColor, stageLabel, statusColor } from "./jobFormat";

type BadgeJob = Pick<JobSummary, "status" | "phase"> & {
  /** Missing on the small job models that carry no stage: the badge then shows the status. */
  stage?: JobSummary["stage"];
  /** Missing on the small job models: no upload line and no info mark are shown. */
  upload?: JobSummary["upload"];
  download?: JobSummary["download"];
  connection?: JobSummary["connection"];
  last_checked_at?: JobSummary["last_checked_at"];
};

type Connection = NonNullable<JobSummary["connection"]>;

/**
 * An info mark for a job whose remote server does not answer. The badge next to it still shows the
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
    `Remote server not answering since ${formatTime(connection.since)} ` +
    `(last try ${formatTime(connection.last_failed_at)}). ${connection.message} ` +
    `This status was last confirmed by the server at ${confirmed}.`;
  return (
    <Tooltip label={label} withArrow multiline w={320}>
      <Text
        component="span"
        size="sm"
        c="orange"
        fw={700}
        aria-label="The remote server is not answering"
        style={{ cursor: "help" }}
      >
        ⓘ
      </Text>
    </Tooltip>
  );
}

/** "3 files sent", or "3 files sent (2 already on the server)" when the server had some. */
function filesSentText(filesDone: number, filesReused: number): string {
  const sent = `${filesDone} ${filesDone === 1 ? "file" : "files"} sent`;
  return filesReused === 0 ? sent : `${sent} (${filesReused} already on the server)`;
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
        {filesSentText(upload.files_done, upload.files_reused)}, waiting for a free upload place
      </Text>
    );
  }
  const percent =
    upload.total_bytes > 0
      ? Math.min(100, Math.floor((upload.sent_bytes / upload.total_bytes) * 100))
      : 0;
  const filesText =
    upload.files_done === 0 ? "" : `, ${filesSentText(upload.files_done, upload.files_reused)}`;
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
 * "Result: 420 KB of 858 KB (48%), continued from 300 KB", with a bar. A download that was cut
 * off keeps what it received, so a later try continues from there instead of starting again.
 */
function DownloadLine({ download }: { download: NonNullable<JobSummary["download"]> }) {
  const known = download.total_bytes > 0;
  const percent = known
    ? Math.min(100, Math.floor((download.received_bytes / download.total_bytes) * 100))
    : 0;
  const size = known
    ? `${formatBytes(download.received_bytes)} of ${formatBytes(download.total_bytes)} (${percent}%)`
    : formatBytes(download.received_bytes);
  const resumed =
    download.resumed_from > 0 ? `, continued from ${formatBytes(download.resumed_from)}` : "";
  return (
    <Stack gap={2} maw={320}>
      {known && <Progress value={percent} size="sm" />}
      <Text size="xs" c="dimmed">
        Result: {size}
        {resumed}
      </Text>
    </Stack>
  );
}

/**
 * The job's stage as a coloured badge (its status when the stage is not known), with the phase
 * next to it while the job is active. An info mark follows when the remote server does not answer
 * (the badge is then the last known state), and an upload or a download of the result in
 * progress shows its bar below.
 */
export function JobStatusBadge({ job }: { job: BadgeJob }) {
  const stage = job.stage;
  const row = (
    <Group gap={6} wrap="nowrap">
      <Badge color={stage ? stageColor(stage) : statusColor(job.status)} variant="light">
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

  if (!job.upload && !job.download) {
    return row;
  }
  return (
    <Stack gap={4}>
      {row}
      {job.upload && <UploadLine upload={job.upload} waiting={stage === "waiting_to_upload"} />}
      {job.download && <DownloadLine download={job.download} />}
    </Stack>
  );
}
