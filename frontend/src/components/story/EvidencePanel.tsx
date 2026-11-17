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
import {
  useEvidence,
  useImportEvidence,
  useWriteEvidenceBrief,
  type EvidenceImport,
  type EvidenceImportClaim,
  type EvidenceRound,
} from "../../api/evidence";
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

const CLAIM_STATUS_LABEL: Record<string, string> = {
  found: "Found",
  partial: "Partly found",
  not_found: "Not found",
  contradicted: "Contradicted",
  blocked: "Blocked",
  no_result: "No result",
  invalid: "Unusable result",
};

const CLAIM_STATUS_COLOR: Record<string, string> = {
  found: "green",
  partial: "yellow",
  not_found: "gray",
  contradicted: "red",
  blocked: "orange",
  no_result: "gray",
  invalid: "red",
};

function claimStatusKey(claim: EvidenceImportClaim): string {
  return claim.status ?? claim.result_state;
}

/** One claim of the import report. Every text shown is plain text. */
function ImportClaimRow({ claim }: { claim: EvidenceImportClaim }) {
  const key = claimStatusKey(claim);
  const refused = claim.items.filter((item) => !item.usable);
  const hasNotes =
    claim.problems.length > 0 ||
    claim.warnings.length > 0 ||
    refused.length > 0 ||
    claim.items.some((item) => item.warnings.length > 0);
  return (
    <Stack gap={2}>
      <Group gap="xs">
        <Text size="sm" fw={600}>
          {claim.claim_id}
        </Text>
        <Badge size="sm" variant="light" color={CLAIM_STATUS_COLOR[key] ?? "gray"}>
          {CLAIM_STATUS_LABEL[key] ?? key}
        </Badge>
        {claim.items.length > 0 && (
          <Text size="xs" c="dimmed">
            {claim.items.filter((item) => item.usable).length} of {claim.items.length} pieces usable
          </Text>
        )}
      </Group>
      {hasNotes && (
        <Stack gap={2} pl="md">
          {claim.problems.map((text) => (
            <Text key={`p-${text}`} size="xs" c="red">
              {text}
            </Text>
          ))}
          {refused.map((item) =>
            item.reasons
              .filter((text) => !claim.problems.includes(text))
              .map((text) => (
                <Text key={`r-${item.evidence_id}-${text}`} size="xs" c="red">
                  {item.evidence_id}: {text}
                </Text>
              )),
          )}
          {claim.warnings.map((text) => (
            <Text key={`w-${text}`} size="xs" c="orange">
              {text}
            </Text>
          ))}
          {claim.items.map((item) =>
            item.warnings.map((text) => (
              <Text key={`iw-${item.evidence_id}-${text}`} size="xs" c="orange">
                {item.evidence_id}: {text}
              </Text>
            )),
          )}
        </Stack>
      )}
    </Stack>
  );
}

function ImportReport({ report }: { report: EvidenceImport }) {
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text size="sm" fw={600}>
          Import {report.version}
        </Text>
        {Object.entries(report.report.by_status).map(([key, count]) => (
          <Badge key={key} size="sm" variant="light" color={CLAIM_STATUS_COLOR[key] ?? "gray"}>
            {CLAIM_STATUS_LABEL[key] ?? key}: {count}
          </Badge>
        ))}
        <Text size="xs" c="dimmed">
          {report.report.usable_items} of {report.report.items} pieces of evidence usable
        </Text>
      </Group>
      {report.claims.map((claim) => (
        <ImportClaimRow key={claim.claim_id} claim={claim} />
      ))}
    </Stack>
  );
}

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
 * then do the research outside the app (a skill in Cursor or Claude). The results are then
 * imported and checked here; the review comes in a later step, and the pipeline waits until it
 * is done.
 */
export function EvidencePanel({ project }: EvidencePanelProps) {
  const { data, isLoading, isError, error } = useEvidence(project.id);
  const write = useWriteEvidenceBrief(project.id);
  const importResults = useImportEvidence(project.id);

  const round = data?.round ?? null;
  const job = data?.job ?? null;
  const failed = job?.status === "failed";
  const importJob = data?.import_job ?? null;
  const importFailed = importJob?.status === "failed";
  const latestImport = data?.latest_import ?? null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={4}>Evidence: research and import</Title>
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
                <Group justify="space-between" align="center">
                  <Text size="xs" c="dimmed">
                    When the agent has finished, import its results: every piece of evidence is
                    checked, and the files that pass are copied into the app.
                  </Text>
                  <Button
                    variant="light"
                    onClick={() => importResults.mutate()}
                    loading={importResults.isPending}
                    disabled={data.can_import !== true}
                  >
                    {latestImport === null ? "Import evidence" : "Import again"}
                  </Button>
                </Group>
                {data.can_import !== true && data.import_blocked_reason !== null && (
                  <Text size="xs" c="dimmed">
                    {data.import_blocked_reason}
                  </Text>
                )}
              </Stack>
            )}
            {latestImport !== null && <ImportReport report={latestImport} />}
          </>
        )}

        {importJob !== null && importJob.status !== "succeeded" && (
          <JobStatusBadge job={importJob} />
        )}
        {importFailed && (
          <Alert color="red" title="The evidence was not imported">
            {importJob.error ?? "The job failed."}
          </Alert>
        )}
        {importResults.isError && (
          <Alert color="red" title="Could not import the evidence">
            {describeError(importResults.error)}
          </Alert>
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
