import {
  Accordion,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useApproveContract,
  useContract,
  type ApproveResponse,
  type ContractSourceOverview,
} from "../../api/gpu";
import { formatDateTime, shortFingerprint } from "../../format";
import { ApiOperations } from "./ApiOperations";
import { ContractDiff } from "./ContractDiff";
import { ContractSourcesEditor } from "./ContractSourcesEditor";

const BASE_LABELS = { gpu: "GPU server", transcription: "Transcription" } as const;

const OUTCOME_LABELS: Record<ApproveResponse["sources"][number]["outcome"], string> = {
  approved: "Approved",
  unchanged: "Already approved",
  unstable: "Changes by itself",
  changed_again: "Changed again",
  unreachable: "Unreachable",
  unreadable: "Cannot be read",
};

function SourceStatusBadge({ source }: { source: ContractSourceOverview }) {
  if (!source.approved) {
    return <Badge color="blue">Not approved</Badge>;
  }
  switch (source.last_check?.status) {
    case "ok":
      return <Badge color="green">Unchanged</Badge>;
    case "changed":
      return <Badge color="yellow">Changed</Badge>;
    case "unreadable":
      return <Badge color="red">Cannot be read</Badge>;
    case "unreachable":
      return <Badge color="red">Unreachable</Badge>;
    default:
      return <Badge color="gray">Approved</Badge>;
  }
}

function SourceCard({ source }: { source: ContractSourceOverview }) {
  const { approved, pending, last_check: check } = source;
  const showCheckMessage = check && check.status !== "ok" && check.message && !pending;

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group gap="xs">
          <Text fw={600}>{source.name}</Text>
          <Badge variant="outline" color="gray">
            {BASE_LABELS[source.base]}
          </Badge>
          <SourceStatusBadge source={source} />
        </Group>
        <Text size="xs" c="dimmed">
          Will call: {source.called_url}
        </Text>

        {approved ? (
          <Text size="sm">
            Version {approved.api_version ?? "unknown"} · fingerprint{" "}
            <Code title={approved.fingerprint}>{shortFingerprint(approved.fingerprint)}</Code> ·
            approved{" "}
            {approved.approved_at ? formatDateTime(approved.approved_at) : "at an unknown time"}
            {approved.operation_count !== null ? ` · ${approved.operation_count} operations` : ""}
          </Text>
        ) : (
          <Text size="sm" c="dimmed">
            Nothing approved yet.
          </Text>
        )}

        {showCheckMessage && (
          <Text size="sm" c={check.status === "not_approved" ? "dimmed" : "red"}>
            Last check: {check.message}
          </Text>
        )}

        {pending && (
          <Alert
            color="yellow"
            title={`Changed: version ${pending.api_version ?? "unknown"}, found ${formatDateTime(
              pending.fetched_at,
            )}`}
          >
            <Stack gap="sm">
              <Text size="xs">
                Approved{" "}
                <Code title={approved?.fingerprint}>
                  {approved ? shortFingerprint(approved.fingerprint) : "none"}
                </Code>{" "}
                now{" "}
                <Code title={pending.fingerprint}>{shortFingerprint(pending.fingerprint)}</Code>
              </Text>
              <ContractDiff diff={pending.diff} />
            </Stack>
          </Alert>
        )}

        {approved && approved.tags.length > 0 && <ApiOperations tags={approved.tags} />}
      </Stack>
    </Paper>
  );
}

function ApproveOutcome({ result }: { result: ApproveResponse }) {
  return (
    <Alert
      color={result.approved ? "green" : "yellow"}
      title={result.approved ? "Approved" : "Nothing was approved"}
    >
      <Stack gap="xs">
        {!result.approved && (
          <Text size="sm">
            Approval is all or nothing: every source must answer the same twice, so none of these
            was recorded.
          </Text>
        )}
        {result.sources.map((item) => (
          <Stack key={item.name} gap={2}>
            <Text size="sm">
              <b>{item.name}</b>: {OUTCOME_LABELS[item.outcome]}
              {item.message ? `. ${item.message}` : ""}
            </Text>
            {item.diff && <ContractDiff diff={item.diff} />}
          </Stack>
        ))}
      </Stack>
    </Alert>
  );
}

/** The approved GPU API, any change waiting for review, and the editor for its sources. */
export function ContractSection() {
  const { data, isLoading, isError, error } = useContract();
  const approve = useApproveContract();

  let body;
  if (isLoading) {
    body = <Loader size="sm" />;
  } else if (isError || !data) {
    body = (
      <Alert color="red" title="Could not load the recorded GPU API">
        {describeError(error)} Press Refresh to try again.
      </Alert>
    );
  } else {
    const anyNotApproved = data.sources.some((item) => item.approved === null);
    const pendingFingerprints = data.sources.flatMap((item) =>
      item.pending ? [[item.name, item.pending.fingerprint] as const] : [],
    );
    const buttonLabel = anyNotApproved
      ? "Capture and approve"
      : pendingFingerprints.length > 0
        ? "Approve this change"
        : null;

    body = (
      <Stack gap="sm">
        {data.sources.every((item) => item.approved === null) && (
          <Text size="sm" c="dimmed">
            Nothing approved yet.
          </Text>
        )}

        {data.sources.map((item) => (
          <SourceCard key={item.name} source={item} />
        ))}

        {buttonLabel && (
          <Group gap="sm">
            <Button
              onClick={() => approve.mutate(Object.fromEntries(pendingFingerprints))}
              loading={approve.isPending}
            >
              {buttonLabel}
            </Button>
            <Text size="xs" c="dimmed">
              Takes a few seconds: each source is fetched twice, a few seconds apart.
            </Text>
          </Group>
        )}

        {approve.isError && (
          <Alert color="red" title="Could not approve">
            {describeError(approve.error)}
          </Alert>
        )}
        {approve.data && <ApproveOutcome result={approve.data} />}

        <Accordion variant="contained" radius="md">
          <Accordion.Item value="sources">
            <Accordion.Control>
              Sources ({data.sources_setting.sources.length}
              {data.sources_setting.source === "saved" ? ", edited" : ", defaults"})
            </Accordion.Control>
            <Accordion.Panel>
              <ContractSourcesEditor
                key={JSON.stringify(data.sources_setting)}
                saved={data.sources_setting}
              />
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </Stack>
    );
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Stack gap={2}>
          <Text fw={600}>GPU API</Text>
          <Text size="sm" c="dimmed">
            The app records your GPU server&apos;s API (its guide and its OpenAPI spec). Once you
            approve it, any difference blocks new GPU jobs until you review and approve the change.
          </Text>
          {data?.last_check ? (
            <Text size="xs" c="dimmed">
              Last API check: {data.last_check.status.replace("_", " ")} at{" "}
              {formatDateTime(data.last_check.checked_at)}
            </Text>
          ) : (
            data && (
              <Text size="xs" c="dimmed">
                The API has not been checked yet for these addresses.
              </Text>
            )
          )}
        </Stack>
        {body}
      </Stack>
    </Paper>
  );
}
