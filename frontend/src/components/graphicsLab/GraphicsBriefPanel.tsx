import { Alert, Badge, Button, ColorSwatch, Group, Loader, Paper, Stack, Table, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useAskGraphicsAgain,
  useMakeAllGraphics,
  useStartGraphicsBrief,
  type GraphicResolved,
  type GraphicRun,
} from "../../api/graphicsLab";
import { KIND_LABELS, OP_LABELS, secondsAt, stateText, TIMING_SOURCE_LABELS } from "./graphicsLabView";

type GraphicsBriefPanelProps = {
  run: GraphicRun;
  /** Opens another run: **Ask again** makes a new run with the same line. */
  onOpenRun: (id: number) => void;
};

const THEME_SWATCHES = [
  "background",
  "surface",
  "text",
  "muted",
  "accent",
  "positive",
  "negative",
  "number",
] as const;

/**
 * The brief of a run: what the director decided and what code worked out from it. The three
 * buttons are paid model calls and start only from a click.
 */
export function GraphicsBriefPanel({ run, onOpenRun }: GraphicsBriefPanelProps) {
  const writeBrief = useStartGraphicsBrief();
  const makeAll = useMakeAllGraphics();
  const askAgain = useAskGraphicsAgain();

  const busy = writeBrief.isPending || makeAll.isPending || askAgain.isPending;
  const writing = run.state === "writing_brief";
  // The brief is resolved from the real word times, so it waits for the voice (GFX-004).
  const waitingForVoice = run.state === "making_voice" || run.state === "voice_failed";
  const noEngineBuilt = run.engines.every((engine) => !engine.built);
  const failure = [writeBrief, makeAll, askAgain].find((click) => click.isError)?.error;
  // A brief job that ended without saying why on the run (cancelled, or failed by a restart).
  const lastError = run.last_error ?? (run.state === "brief_failed" ? run.brief_job?.error : null);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text size="xs" fw={600} c="dimmed">
              Brief
            </Text>
            <Group gap="xs">
              {(writing || run.state === "making_voice") && <Loader size="xs" />}
              <Text size="sm" c="dimmed">
                {stateText(run.state)}.
              </Text>
            </Group>
          </Stack>

          <Group gap="xs">
            {!waitingForVoice && (run.state === "new" || run.state === "brief_failed") && (
              <Button
                size="compact-sm"
                variant="default"
                loading={writeBrief.isPending}
                disabled={busy}
                onClick={() => writeBrief.mutate(run.id)}
              >
                {run.state === "new" ? "Write the brief" : "Try again"}
              </Button>
            )}
            {!waitingForVoice && run.state !== "writing_brief" && (
              <Button
                size="compact-sm"
                loading={makeAll.isPending}
                disabled={busy || (run.state === "brief_ready" && noEngineBuilt)}
                onClick={() => makeAll.mutate(run.id)}
              >
                Make all
              </Button>
            )}
            {run.state === "brief_ready" && (
              <Button
                size="compact-sm"
                variant="default"
                loading={askAgain.isPending}
                disabled={busy}
                onClick={() => askAgain.mutate(run.id, { onSuccess: (made) => onOpenRun(made.id) })}
              >
                Ask again
              </Button>
            )}
          </Group>
        </Group>

        {waitingForVoice && (
          <Text size="xs" c="dimmed">
            {run.state === "making_voice"
              ? "The brief can be written once the voice is timed."
              : "The voice failed. Make a new run to try again."}
          </Text>
        )}
        {!waitingForVoice && run.state !== "brief_ready" && run.state !== "writing_brief" && (
          <Text size="xs" c="dimmed">
            Writing the brief is one paid model call (two at most, if the first answer cannot be
            used). Make all writes the brief and then starts the building blocks and the generated
            component.
          </Text>
        )}
        {run.state === "brief_ready" && noEngineBuilt && (
          <Text size="xs" c="dimmed">
            No engine is built yet, so Make all has nothing to start. Ask again makes a new run with
            the same line and a new brief.
          </Text>
        )}

        {failure !== undefined && (
          <Alert color="red" title="That did not start">
            {describeError(failure)}
          </Alert>
        )}
        {lastError && (
          <Text size="sm" c="red" style={{ wordBreak: "break-word" }}>
            {lastError}
          </Text>
        )}

        {run.brief !== null && run.resolved !== null && <BriefDetails run={run} resolved={run.resolved} />}
      </Stack>
    </Paper>
  );
}

function BriefDetails({ run, resolved }: { run: GraphicRun; resolved: GraphicResolved }) {
  const brief = run.brief;
  if (brief === null) {
    return null;
  }
  const seconds = (resolved.frames / resolved.fps).toFixed(1);

  return (
    <Stack gap="md">
      <Group gap="xs">
        <Badge variant="light">{KIND_LABELS[brief.kind]}</Badge>
        <Text size="xs" c="dimmed">
          {resolved.frames} frames, {seconds} s. Times are {TIMING_SOURCE_LABELS[resolved.timing_source] ?? resolved.timing_source}.
        </Text>
      </Group>

      <Stack gap={2}>
        <Text size="sm" fw={600}>
          {brief.intent}
        </Text>
        <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {brief.visual_brief}
        </Text>
      </Stack>

      {(brief.facts.length > 0 || brief.derived.length > 0) && (
        <Table.ScrollContainer minWidth={420}>
          <Table withTableBorder verticalSpacing={4} fz="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Id</Table.Th>
                <Table.Th>Number</Table.Th>
                <Table.Th>On screen</Table.Th>
                <Table.Th>Where it comes from</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {brief.facts.map((fact) => (
                <Table.Tr key={fact.id}>
                  <Table.Td>{fact.id}</Table.Td>
                  <Table.Td>{fact.label}</Table.Td>
                  <Table.Td fw={600}>{resolved.facts[fact.id]?.display}</Table.Td>
                  <Table.Td>said in the line as &ldquo;{fact.said_as}&rdquo;</Table.Td>
                </Table.Tr>
              ))}
              {brief.derived.map((item) => (
                <Table.Tr key={item.id}>
                  <Table.Td>{item.id}</Table.Td>
                  <Table.Td>{item.label}</Table.Td>
                  <Table.Td fw={600}>{resolved.derived[item.id]?.display}</Table.Td>
                  <Table.Td>
                    worked out by code: {OP_LABELS[item.op]} of {item.of.join(", ")}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {brief.facts.length === 0 && (
        <Text size="xs" c="dimmed">
          No numbers: the graphic shows no figures.
        </Text>
      )}

      <Table.ScrollContainer minWidth={420}>
        <Table withTableBorder verticalSpacing={4} fz="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Beat</Table.Th>
              <Table.Th>At</Table.Th>
              <Table.Th>When the line says</Table.Th>
              <Table.Th>What appears</Table.Th>
              <Table.Th>Shows</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {brief.beats.map((beat) => (
              <Table.Tr key={beat.id}>
                <Table.Td>{beat.id}</Table.Td>
                <Table.Td>
                  {secondsAt(resolved.beats[beat.id]?.frame ?? 0, resolved.fps)} (frame{" "}
                  {resolved.beats[beat.id]?.frame})
                </Table.Td>
                <Table.Td>&ldquo;{beat.phrase}&rdquo;</Table.Td>
                <Table.Td>{beat.shows}</Table.Td>
                <Table.Td>{beat.refs.join(", ")}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>

      <Stack gap={4}>
        <Group gap="md">
          {THEME_SWATCHES.map((name) => (
            <Group key={name} gap={6}>
              <ColorSwatch color={resolved.theme[name]} size={18} withShadow />
              <Text size="xs" c="dimmed">
                {name} {resolved.theme[name]}
              </Text>
            </Group>
          ))}
        </Group>
        <Text size="xs" c="dimmed">
          {brief.theme.palette} palette, {resolved.theme.background_style} background,{" "}
          {resolved.theme.motion} motion, {brief.theme.mood}. Safe area {resolved.safe_area.left},{" "}
          {resolved.safe_area.top} to {resolved.safe_area.right}, {resolved.safe_area.bottom}; captions
          take {resolved.caption_zone.top} to {resolved.caption_zone.bottom} from the top.
        </Text>
      </Stack>

      {resolved.notes.map((note) => (
        <Text key={note} size="xs" c="orange" style={{ wordBreak: "break-word" }}>
          {note}
        </Text>
      ))}
    </Stack>
  );
}
