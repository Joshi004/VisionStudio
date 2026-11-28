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
  useContinueWithoutFootage,
  useFootage,
  useImportFootage,
  useUndoNoFootage,
  useWriteFootageBrief,
  type FootageImport,
  type FootageImportMark,
  type FootageMarkState,
  type FootageRound,
} from "../../api/footage";
import type { ProjectDetail } from "../../api/projects";
import { formatDateTime } from "../../format";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { CLAIM_STATUS_COLOR, CLAIM_STATUS_LABEL } from "./evidenceLabels";

type FootagePanelProps = {
  project: ProjectDetail;
};

const ROUND_STATUS_LABEL: Record<FootageRound["status"], string> = {
  brief_written: "Brief written, waiting for the research",
  imported: "Results imported, waiting for your review",
  reviewed: "Reviewed",
};

const MARK_STATE_LABEL: Record<FootageMarkState["state"], string> = {
  owner_file: "Your file",
  reviewed: "Reviewed",
  no_footage: "No footage here",
  waiting: "Waiting for research",
};

const MARK_STATE_COLOR: Record<FootageMarkState["state"], string> = {
  owner_file: "green",
  reviewed: "green",
  no_footage: "gray",
  waiting: "orange",
};

function markStatusKey(mark: FootageImportMark): string {
  return mark.status ?? mark.result_state;
}

/** One mark of the import report. Every text shown is plain text. */
function ImportMarkRow({ mark }: { mark: FootageImportMark }) {
  const key = markStatusKey(mark);
  const refused = mark.items.filter((item) => !item.usable);
  const hasNotes =
    mark.problems.length > 0 ||
    mark.warnings.length > 0 ||
    refused.length > 0 ||
    mark.items.some((item) => item.warnings.length > 0);
  return (
    <Stack gap={2}>
      <Group gap="xs">
        <Text size="sm" fw={600}>
          {mark.mark_id}
        </Text>
        <Badge size="sm" variant="light" color={CLAIM_STATUS_COLOR[key] ?? "gray"}>
          {CLAIM_STATUS_LABEL[key] ?? key}
        </Badge>
        {mark.items.length > 0 && (
          <Text size="xs" c="dimmed">
            {mark.items.filter((item) => item.usable).length} of {mark.items.length} pieces usable
          </Text>
        )}
      </Group>
      {hasNotes && (
        <Stack gap={2} pl="md">
          {mark.problems.map((text) => (
            <Text key={`p-${text}`} size="xs" c="red">
              {text}
            </Text>
          ))}
          {refused.map((item) =>
            item.reasons
              .filter((text) => !mark.problems.includes(text))
              .map((text) => (
                <Text key={`r-${item.piece_id}-${text}`} size="xs" c="red">
                  {item.piece_id}: {text}
                </Text>
              )),
          )}
          {mark.warnings.map((text) => (
            <Text key={`w-${text}`} size="xs" c="orange">
              {text}
            </Text>
          ))}
          {mark.items.map((item) =>
            item.warnings.map((text) => (
              <Text key={`iw-${item.piece_id}-${text}`} size="xs" c="orange">
                {item.piece_id}: {text}
              </Text>
            )),
          )}
        </Stack>
      )}
    </Stack>
  );
}

function ImportReport({ report }: { report: FootageImport }) {
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
          {report.report.usable_items} of {report.report.items} pieces of footage usable
        </Text>
      </Group>
      {report.marks.map((mark) => (
        <ImportMarkRow key={mark.mark_id} mark={mark} />
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
 * The footage step: write the brief of the marks that have no footage yet into the files folder,
 * then do the research outside the app (a skill in Cursor or Claude). Only the full render waits
 * for it. "Continue without footage" lets the render go on with the shots already planned. When
 * the agent has finished, its results are imported and checked here; the review comes later
 * (FTG-012).
 */
export function FootagePanel({ project }: FootagePanelProps) {
  const { data, isLoading, isError, error } = useFootage(project.id);
  const write = useWriteFootageBrief(project.id);
  const continueWithout = useContinueWithoutFootage(project.id);
  const undo = useUndoNoFootage(project.id);
  const importResults = useImportFootage(project.id);

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
          <Title order={4}>Footage: research and review</Title>
          <Group gap="xs">
            <Button
              variant="light"
              onClick={() => continueWithout.mutate()}
              loading={continueWithout.isPending}
              disabled={isLoading || isError || data?.can_continue_without !== true}
            >
              Continue without footage
            </Button>
            <Button
              onClick={() => write.mutate()}
              loading={write.isPending}
              disabled={isLoading || isError || data?.can_write_brief !== true}
            >
              {round === null ? "Write the brief" : "Write a new round"}
            </Button>
          </Group>
        </Group>
        <Text size="xs" c="dimmed">
          A new round lists only the marks that have no footage yet, with the sentences around
          them. Research happens outside the app: paste the prompt below into Cursor or Claude, in
          the round&apos;s folder. Only the video render waits for footage; everything else keeps
          going.
        </Text>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the footage">
            {describeError(error)}
          </Alert>
        )}
        {data?.wanted === false && (
          <Alert color="gray" title="No footage for this project">
            Footage is for a continuous explainer with footage switched on.
          </Alert>
        )}

        {data?.wanted === true && (
          <>
            <Group gap="xs">
              <Badge variant="light">
                {data.marks_count} {data.marks_count === 1 ? "mark counts" : "marks count"}
              </Badge>
              {data.covered_marks > 0 && (
                <Badge color="green" variant="light">
                  {data.covered_marks} with footage
                </Badge>
              )}
              {data.skipped_marks > 0 && (
                <Badge color="gray" variant="light">
                  {data.skipped_marks} with no footage
                </Badge>
              )}
              {data.waiting_marks > 0 && (
                <Badge color="orange" variant="light">
                  {data.waiting_marks} waiting for research
                </Badge>
              )}
              {round !== null && (
                <Badge color={round.status === "reviewed" ? "green" : "orange"} variant="light">
                  Round {round.round_no}: {ROUND_STATUS_LABEL[round.status]}
                </Badge>
              )}
              {round?.out_of_date === true && (
                <Badge color="yellow" variant="light">
                  New marks since this brief
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

            {data.marks.length > 0 && (
              <Stack gap={4}>
                {data.marks.map((mark) => (
                  <Group key={mark.id} gap="xs" wrap="nowrap" align="center">
                    <Text size="sm" fw={600}>
                      {mark.id}
                    </Text>
                    <Badge size="sm" variant="light" color={MARK_STATE_COLOR[mark.state]}>
                      {MARK_STATE_LABEL[mark.state]}
                    </Badge>
                    <Text size="sm" lineClamp={1} style={{ flex: 1, minWidth: 0 }}>
                      {mark.text}
                    </Text>
                    {mark.state === "no_footage" && (
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        onClick={() => undo.mutate(mark.id)}
                        loading={undo.isPending && undo.variables === mark.id}
                      >
                        Undo
                      </Button>
                    )}
                  </Group>
                ))}
              </Stack>
            )}

            {round !== null && (
              <Stack gap="xs">
                <Text size="sm">
                  Round {round.round_no} carries {round.marks}{" "}
                  {round.marks === 1 ? "mark" : "marks"} and was written{" "}
                  {formatDateTime(round.created_at)}.
                </Text>
                {round.host_folder !== null ? (
                  <CopyLine label="Folder (on your Mac)" value={round.host_folder} />
                ) : (
                  <Text size="sm">
                    The folder is <Code>{round.folder}</Code> inside the files folder. Set the
                    files folder through <Code>docker-compose.files.yml</Code> to see its path on
                    your Mac here.
                  </Text>
                )}
                <CopyLine label={`Prompt (skill: ${data.skill})`} value={data.prompt} />
                <Group justify="space-between" align="center">
                  <Text size="xs" c="dimmed">
                    When the agent has finished, import its results: every piece of footage is
                    checked, and the files that pass are copied into the app.
                  </Text>
                  <Button
                    variant="light"
                    onClick={() => importResults.mutate()}
                    loading={importResults.isPending}
                    disabled={data.can_import !== true}
                  >
                    {latestImport === null ? "Import footage" : "Import again"}
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
          <Alert color="red" title="The footage was not imported">
            {importJob.error ?? "The job failed."}
          </Alert>
        )}
        {importResults.isError && (
          <Alert color="red" title="Could not import the footage">
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
        {continueWithout.isError && (
          <Alert color="red" title="Could not continue without footage">
            {describeError(continueWithout.error)}
          </Alert>
        )}
        {undo.isError && (
          <Alert color="red" title="Could not undo the choice">
            {describeError(undo.error)}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
