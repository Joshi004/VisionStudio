import {
  Alert,
  Badge,
  Button,
  Code,
  CopyButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { useEvidence, useWriteEvidenceBrief, type EvidenceRound } from "../../api/evidence";
import type { ProjectDetail } from "../../api/projects";
import { formatDateTime } from "../../format";
import { JobStatusBadge } from "../jobs/JobStatusBadge";

type EvidencePanelProps = {
  project: ProjectDetail;
};

const ROUND_STATUS_LABEL: Record<EvidenceRound["status"], string> = {
  brief_written: "Brief written, waiting for the research",
  imported: "Results imported, waiting for your review",
  reviewed: "Reviewed",
};

function CopyLine({ label, value }: { label: string; value: string }) {
  return (
    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
      <Stack gap={2} style={{ minWidth: 0 }}>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Code block style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {value}
        </Code>
      </Stack>
      <CopyButton value={value}>
        {({ copied, copy }) => (
          <Button size="xs" variant="light" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </Button>
        )}
      </CopyButton>
    </Group>
  );
}

/**
 * The research step of the evidence layer: write the brief of the claims into the files folder,
 * then do the research outside the app (a skill in Cursor or Claude). The importing and the
 * review come in later steps; the pipeline waits here until they are done.
 */
export function EvidencePanel({ project }: EvidencePanelProps) {
  const { data, isLoading, isError, error } = useEvidence(project.id);
  const write = useWriteEvidenceBrief(project.id);

  const round = data?.round ?? null;
  const job = data?.job ?? null;
  const failed = job?.status === "failed";

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={4}>Evidence: the research brief</Title>
          <Button
            onClick={() => write.mutate()}
            loading={write.isPending}
            disabled={isLoading || isError || data?.can_write_brief !== true}
          >
            {round === null ? "Write the brief" : "Write a new round"}
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          The brief lists the claims that count now, with the sentences around them. Research
          happens outside the app: paste the prompt below into Cursor or Claude, in the round's
          folder.
        </Text>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the evidence">
            {describeError(error)}
          </Alert>
        )}
        {data?.wanted === false && (
          <Alert color="gray" title="No evidence for this project">
            Evidence is for a continuous explainer with evidence switched on.
          </Alert>
        )}

        {data?.wanted === true && (
          <>
            <Group gap="xs">
              <Badge variant="light">
                {data.claims_count} {data.claims_count === 1 ? "claim counts" : "claims count"}
              </Badge>
              {round !== null && (
                <Badge color={round.status === "reviewed" ? "green" : "orange"} variant="light">
                  Round {round.round_no}: {ROUND_STATUS_LABEL[round.status]}
                </Badge>
              )}
              {round?.out_of_date === true && (
                <Badge color="yellow" variant="light">
                  Claims changed since this brief
                </Badge>
              )}
            </Group>

            {data.awaiting !== null && (
              <Alert color="orange" title="Waiting for you">
                {data.awaiting}
              </Alert>
            )}
            {data.blocked_reason !== null && data.awaiting === null && (
              <Text size="sm" c="dimmed">
                {data.blocked_reason}
              </Text>
            )}

            {round !== null && (
              <Stack gap="xs">
                <Text size="sm">
                  Round {round.round_no} carries {round.claims}{" "}
                  {round.claims === 1 ? "claim" : "claims"} and was written{" "}
                  {formatDateTime(round.created_at)}.
                </Text>
                {round.host_folder !== null ? (
                  <CopyLine label="Folder (on your Mac)" value={round.host_folder} />
                ) : (
                  <Text size="sm">
                    The folder is <Code>{round.folder}</Code> inside the files folder. Set the
                    files folder through <Code>docker-compose.files.yml</Code> to see its path
                    on your Mac here.
                  </Text>
                )}
                <CopyLine label={`Prompt (skill: ${data.skill})`} value={data.prompt} />
              </Stack>
            )}
          </>
        )}

        {job !== null && job.status !== "succeeded" && <JobStatusBadge job={job} />}
        {failed && (
          <Alert color="red" title="The brief was not written">
            {job.error ?? "The job failed."}
          </Alert>
        )}
        {write.isError && (
          <Alert color="red" title="Could not write the brief">
            {describeError(write.error)}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
