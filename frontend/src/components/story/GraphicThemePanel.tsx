import { useState } from "react";
import {
  Alert,
  Button,
  ColorSwatch,
  Group,
  List,
  Loader,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useGraphicTheme,
  useGraphicThemeVersion,
  useRunGraphicTheme,
  type GraphicThemeColours,
  type GraphicThemeOut,
} from "../../api/graphicTheme";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { FeedbackBadge } from "./FeedbackBadge";
import { FeedbackModal } from "./FeedbackModal";

type GraphicThemePanelProps = {
  projectId: number;
};

const COLOUR_LABELS: Record<keyof GraphicThemeColours, string> = {
  background: "Background",
  surface: "Surface",
  text: "Text",
  muted: "Muted text",
  accent: "Accent",
  positive: "Positive",
  negative: "Negative",
  number: "Numbers",
};

const BACKGROUND_LABELS: Record<string, string> = {
  solid: "Solid",
  gradient: "Gradient",
  grid: "Grid",
  glow: "Glow",
};

const MOTION_LABELS: Record<string, string> = {
  snappy: "Snappy",
  smooth: "Smooth",
  calm: "Calm",
};

/**
 * The graphics theme stage of a continuous explainer: the one look every chart, diagram and text
 * card of the video shares. The model writes it from the Story Bible. Run / Write again makes a
 * new version, and Write again with a note gives the model what to change.
 */
export function GraphicThemePanel({ projectId }: GraphicThemePanelProps) {
  const { data, isLoading, isError, error } = useGraphicTheme(projectId);
  const run = useRunGraphicTheme(projectId);
  const [noting, setNoting] = useState(false);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useGraphicThemeVersion(projectId, viewingOlder ? shownVersion : null);
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);
  const notWanted = data !== undefined && !data.wanted;
  const blocked = data?.blocked_reason ?? null;
  const cannotRun = isLoading || isError || notWanted || blocked !== null;

  const startRun = (feedback?: string) => {
    // A new version is on its way: show it when it arrives.
    setPicked(null);
    run.mutate({ feedback });
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Graphics look</Title>
              <Text size="sm" c="dimmed">
                The one look every chart, diagram and text card of this video shares: the colours,
                the background, how fast things move and the mood. The model writes it from the
                Story Bible.
              </Text>
            </Stack>
            <Group gap="sm" align="flex-end">
              {data && data.versions.length > 1 && (
                <Select
                  aria-label="Version"
                  w={190}
                  allowDeselect={false}
                  data={data.versions.map((version, index) => ({
                    value: String(version.version),
                    label: `Version ${version.version}${index === 0 ? " (newest)" : ""}`,
                  }))}
                  value={shownVersion === null ? null : String(shownVersion)}
                  onChange={(value) => value !== null && setPicked(Number(value))}
                />
              )}
              <Button
                variant="default"
                onClick={() => setNoting(true)}
                disabled={cannotRun || latest === null || active}
              >
                Write again with a note
              </Button>
              <Button
                onClick={() => startRun()}
                loading={run.isPending || active}
                disabled={cannotRun}
              >
                {latest ? "Write again" : "Run"}
              </Button>
            </Group>
          </Group>

          {blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the graphics look">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the graphics look">
              {describeError(run.error)}
            </Alert>
          )}
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          {job?.status === "failed" && (
            <Alert color="red" title="The last run failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {data?.out_of_date && !viewingOlder && !notWanted && (
            <Alert color="yellow" title="Out of date">
              <Stack gap={4}>
                <Text size="sm">
                  Something this look was written from has changed. Press Write again to make a
                  new one.
                </Text>
                {data.reasons.length > 0 && (
                  <List size="sm">
                    {data.reasons.map((reason) => (
                      <List.Item key={reason}>{reason}</List.Item>
                    ))}
                  </List>
                )}
              </Stack>
            </Alert>
          )}
        </Stack>
      </Paper>

      {shown && <GraphicThemeView theme={shown} />}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}

      <FeedbackModal
        opened={noting}
        title="Feedback on the graphics look"
        what="the graphics look"
        initialText={latest?.feedback ?? ""}
        writtenByUser={false}
        submitLabel="Write with feedback"
        onCancel={() => setNoting(false)}
        onSubmit={(text) => {
          setNoting(false);
          startRun(text);
        }}
      />
    </Stack>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm" fw={500}>
        {value}
      </Text>
    </Stack>
  );
}

function GraphicThemeView({ theme }: { theme: GraphicThemeOut }) {
  const { content, colours } = theme;
  const look = content.theme;
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs">
            <Text size="xs" c="dimmed">
              Version {theme.version}, written by the model.
            </Text>
            <FeedbackBadge text={theme.feedback} />
          </Group>
        </Group>

        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
          {(Object.keys(COLOUR_LABELS) as (keyof GraphicThemeColours)[]).map((key) => (
            <Group key={key} gap={8} wrap="nowrap">
              <ColorSwatch color={colours[key]} size={22} />
              <Stack gap={0}>
                <Text size="sm">{COLOUR_LABELS[key]}</Text>
                <Text size="xs" c="dimmed">
                  {colours[key]}
                </Text>
              </Stack>
            </Group>
          ))}
        </SimpleGrid>

        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
          <Detail label="Palette" value={look.palette === "dark" ? "Dark" : "Light"} />
          <Detail label="Background" value={BACKGROUND_LABELS[look.background] ?? look.background} />
          <Detail label="Motion" value={MOTION_LABELS[look.motion] ?? look.motion} />
          <Detail label="Mood" value={look.mood} />
        </SimpleGrid>

        <Text size="sm">{content.reason}</Text>

        {content.notes.map((note) => (
          <Alert key={note} color="yellow" title="Accent colour changed">
            {note}
          </Alert>
        ))}
      </Stack>
    </Paper>
  );
}
