import {
  Alert,
  Badge,
  Button,
  CopyButton,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useGraphicsTrial,
  useGraphicsTrials,
  type GraphicTrialRun,
  type GraphicTrialSummary,
} from "../../api/graphicsLab";
import { ORIENTATION_LABELS, snippet, stateText } from "./graphicsLabView";
import {
  measureRows,
  NUMBERS_NOTE,
  OUTCOME_COLORS,
  OUTCOME_LABELS,
  trialMarkdown,
} from "./graphicsTrialView";

type GraphicsTrialSummaryProps = {
  setNo: number;
  /** Back to the list of runs and the trial form. */
  onBack: () => void;
  /** Shows another set. */
  onOpenTrial: (setNo: number) => void;
  /** Opens one run of the set (its page goes over the summary). */
  onOpenRun: (runId: number) => void;
};

function EngineTable({ summary }: { summary: GraphicTrialSummary }) {
  const rows = measureRows(summary.engines);
  return (
    <ScrollArea>
      <Table withTableBorder withColumnBorders fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Measure</Table.Th>
            {summary.engines.map((engine) => (
              <Table.Th key={engine.key}>{engine.label}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.name}>
              <Table.Td fw={500}>{row.name}</Table.Td>
              {row.values.map((value, index) => (
                <Table.Td key={summary.engines[index].key}>{value}</Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

function OutcomeBadge({ run, engineKey }: { run: GraphicTrialRun; engineKey: string }) {
  const outcome = run.outcomes[engineKey];
  if (outcome === undefined) {
    return null;
  }
  return (
    <Stack gap={2} align="flex-start">
      <Badge color={OUTCOME_COLORS[outcome.kind]} variant="light">
        {OUTCOME_LABELS[outcome.kind]}
      </Badge>
      {outcome.kind === "video" && (
        <Text size="xs" c="dimmed">
          {outcome.verdict ?? "not judged"}
          {outcome.attempt !== null && outcome.attempt > 1 ? ` · attempt ${outcome.attempt}` : ""}
        </Text>
      )}
    </Stack>
  );
}

function RunsTable({
  summary,
  onOpenRun,
}: {
  summary: GraphicTrialSummary;
  onOpenRun: (runId: number) => void;
}) {
  return (
    <ScrollArea>
      <Table withTableBorder withColumnBorders fz="sm" verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Excerpt</Table.Th>
            {summary.engines.map((engine) => (
              <Table.Th key={engine.key}>{engine.label}</Table.Th>
            ))}
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {summary.runs.map((run) => (
            <Table.Tr key={run.run_id}>
              <Table.Td maw={260}>
                <Group gap="xs" wrap="nowrap" align="flex-start">
                  <Badge variant="outline" style={{ flexShrink: 0 }}>
                    {run.case}
                  </Badge>
                  <Stack gap={2}>
                    <Text size="xs" style={{ wordBreak: "break-word" }}>
                      {snippet(run.line_text, 70)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {ORIENTATION_LABELS[run.orientation]} · run {run.run_id} ·{" "}
                      {stateText(run.state)}
                    </Text>
                    {run.last_error !== null && (
                      <Text size="xs" c="red" style={{ wordBreak: "break-word" }}>
                        {run.last_error}
                      </Text>
                    )}
                  </Stack>
                </Group>
              </Table.Td>
              {summary.engines.map((engine) => (
                <Table.Td key={engine.key}>
                  <OutcomeBadge run={run} engineKey={engine.key} />
                </Table.Td>
              ))}
              <Table.Td>
                <Button size="compact-xs" variant="subtle" onClick={() => onOpenRun(run.run_id)}>
                  Open run
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

/**
 * The summary of one trial set (GFX-012, §4.9): for each engine, over the set's runs, how many
 * made a video, how many said no template fits, how many passed the checks, the medians, the
 * repeat results and the verdicts; then each run's result on each engine with a link to the run.
 * It is read again while anything of the set is still going. **Copy as Markdown** puts it in the
 * form Appendix B takes.
 */
export function GraphicsTrialSummary({
  setNo,
  onBack,
  onOpenTrial,
  onOpenRun,
}: GraphicsTrialSummaryProps) {
  const trial = useGraphicsTrial(setNo);
  const sets = useGraphicsTrials().data?.sets ?? [];
  const summary = trial.data;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Button variant="subtle" size="compact-sm" onClick={onBack}>
          ← All runs
        </Button>
        {sets.length > 1 && (
          <Select
            size="xs"
            aria-label="Trial set"
            data={sets.map((item) => ({ value: String(item.set_no), label: `Set ${item.set_no}` }))}
            value={String(setNo)}
            onChange={(value) => value !== null && onOpenTrial(Number(value))}
            allowDeselect={false}
            w={140}
          />
        )}
      </Group>

      {trial.isLoading && <Loader size="sm" />}
      {trial.isError && (
        <Alert color="red" title="Could not load the trial">
          {describeError(trial.error)}
        </Alert>
      )}

      {summary && (
        <>
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Trial set {summary.set_no}</Title>
              <Text size="xs" c="dimmed">
                {new Date(summary.created_at).toLocaleString()} ·{" "}
                {summary.with_voice ? "with a voice" : "no voice"} · {summary.runs.length} runs
              </Text>
            </Stack>
            <Group gap="xs">
              {summary.active && (
                <Group gap={6}>
                  <Loader size="xs" />
                  <Text size="xs" c="dimmed">
                    Still working. This page updates by itself.
                  </Text>
                </Group>
              )}
              <CopyButton value={trialMarkdown(summary)}>
                {({ copied, copy }) => (
                  <Button size="compact-sm" variant="default" onClick={copy}>
                    {copied ? "Copied" : "Copy as Markdown"}
                  </Button>
                )}
              </CopyButton>
            </Group>
          </Group>

          <Paper withBorder p="md" radius="md">
            <Stack gap="xs">
              <Text size="sm" fw={600}>
                Each engine over the set
              </Text>
              <EngineTable summary={summary} />
              <Text size="xs" c="dimmed">
                A render that was made again does not change these counts: they read the newest
                attempt that is not a Render again, which is the one you judge. {NUMBERS_NOTE}
              </Text>
            </Stack>
          </Paper>

          <Paper withBorder p="md" radius="md">
            <Stack gap="xs">
              <Text size="sm" fw={600}>
                Each run
              </Text>
              <RunsTable summary={summary} onOpenRun={onOpenRun} />
            </Stack>
          </Paper>
        </>
      )}
    </Stack>
  );
}
