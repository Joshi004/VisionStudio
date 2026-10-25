import { useState } from "react";
import { Link } from "react-router";
import {
  Alert,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useMusicPlan,
  useMusicPlanVersion,
  useRunMusicPlan,
  useSaveMusicPlan,
  type MusicPlanCue,
  type MusicPlanOut,
} from "../../api/musicPlan";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ReplaceManualModal } from "../story/ReplaceManualModal";
import { MusicPlanEditor } from "./MusicPlanEditor";
import { MusicPlanStrip } from "./MusicPlanStrip";
import {
  JOIN_LABELS,
  KIND_COLORS,
  KIND_LABELS,
  MAKER_LABELS,
  END_STYLE_LABELS,
  START_STYLE_LABELS,
  cueTimes,
  describeAnchor,
  formatSeconds,
  refLabel,
} from "./musicPlanView";

type MusicPlanPanelProps = {
  projectId: number;
};

const LENS_LABELS: Record<string, string> = {
  dramatic_fit: "Dramatic fit",
  variety_restraint: "Variety and restraint",
  theme_use: "Use of the themes",
  joins: "Joins",
  cue_detail: "Objections of the cues",
};

/**
 * The music plan stage: the plan as one line per cue, a time strip of the whole story, what the
 * four critics said in each round, and a form to edit it. Run / Re-run writes a new version from
 * the model; Edit saves one written by you. When music is switched off, the panel only says so.
 */
export function MusicPlanPanel({ projectId }: MusicPlanPanelProps) {
  const { data, isLoading, isError, error } = useMusicPlan(projectId);
  const run = useRunMusicPlan(projectId);
  const save = useSaveMusicPlan(projectId);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useMusicPlanVersion(projectId, viewingOlder ? shownVersion : null);
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);
  const musicOff = data !== undefined && !data.music_enabled;
  const blocked = data?.blocked_reason ?? null;

  const startRun = (confirmReplaceManual: boolean) => {
    // A new version is on its way: show it when it arrives.
    setPicked(null);
    run.mutate({ confirmReplaceManual });
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Music plan</Title>
              <Text size="sm" c="dimmed">
                Where the score, the ambience, the hits and the silence go across the whole story,
                written once and reviewed by four critics before any music is made.
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
                onClick={() => {
                  save.reset();
                  setPicked(null);
                  setEditing(true);
                }}
                disabled={
                  musicOff ||
                  editing ||
                  latest === null ||
                  data?.timeline == null ||
                  active ||
                  blocked !== null
                }
              >
                Edit
              </Button>
              <Button
                onClick={() => (data?.needs_confirmation ? setConfirming(true) : startRun(false))}
                loading={run.isPending || active}
                disabled={isLoading || isError || editing || musicOff || blocked !== null}
              >
                {latest ? "Re-run" : "Run"}
              </Button>
            </Group>
          </Group>

          {!musicOff && blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {musicOff && (
            <Alert color="gray" title="Music is switched off">
              This project is made without music, so this step is skipped. Turn music on in the{" "}
              <Link to={`/projects/${projectId}/settings`}>project settings</Link> to plan it.
            </Alert>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the music plan">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the music plan">
              {describeError(run.error)}
            </Alert>
          )}
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          {job?.status === "failed" && (
            <Alert color="red" title="The last run failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {data?.out_of_date && !viewingOlder && !musicOff && (
            <Alert color="yellow" title="Out of date">
              <Stack gap={4}>
                <Text size="sm">
                  Something this plan was written from has changed. Press Re-run to write a new
                  one.
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

      {editing && latest && data?.timeline && (
        <Paper withBorder p="md" radius="md">
          <MusicPlanEditor
            initial={latest.content}
            timeline={data.timeline}
            themes={data.themes}
            saving={save.isPending}
            error={save.error}
            onSave={(content) => save.mutate(content, { onSuccess: () => setEditing(false) })}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {shown && !editing && <MusicPlanView plan={shown} />}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}
      <ReplaceManualModal
        opened={confirming}
        title="Run the music plan again?"
        what="The newest music plan"
        confirmLabel="Re-run"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          startRun(true);
        }}
      />
    </Stack>
  );
}

function sourceLabel(source: string) {
  return source === "manual" ? "written by you" : "written by the model";
}

/** The plan as text over the time strip, then its numbers and what the critics said. */
function MusicPlanView({ plan }: { plan: MusicPlanOut }) {
  const { content, facts, timeline } = plan;
  const joinFrom = new Map(content.boundaries.map((item) => [item.from_cue, item]));
  const soundRequests = content.sound_requests;

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group gap="sm">
            <Title order={5}>The plan</Title>
            <Text size="xs" c="dimmed">
              Version {plan.version}, {sourceLabel(plan.source)}, {formatSeconds(timeline.total_s)}{" "}
              of story
            </Text>
          </Group>
          <MusicPlanStrip timeline={timeline} cues={content.cues} />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          {content.cues.length === 0 && (
            <Text size="sm" c="dimmed">
              The plan has no cues: the story is told without music.
            </Text>
          )}
          {content.cues.map((cue) => {
            const join = joinFrom.get(cue.id);
            return (
              <Stack key={cue.id} gap={2}>
                <CueLine cue={cue} />
                <Text size="xs" c="dimmed">
                  {cue.purpose}
                </Text>
                <Text size="xs" c="dimmed">
                  {anchorLines(cue, timeline)}
                </Text>
                {cue.rerouted && (
                  <Text size="xs" c="orange">
                    {cue.rerouted.reason}
                  </Text>
                )}
                {join && (
                  <Text size="xs" c="dimmed">
                    Then, a {JOIN_LABELS[join.join] ?? join.join}: {join.reason}
                  </Text>
                )}
              </Stack>
            );
          })}
        </Stack>
      </Paper>

      {soundRequests.length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Stack gap={4}>
            <Title order={5}>Sound requests for H3</Title>
            <List size="sm">
              {soundRequests.map((request) => (
                <List.Item key={request.cue_id}>
                  {request.cue_id}: {refLabel(timeline, request.event)} in{" "}
                  {refLabel(timeline, request.shot)}
                </List.Item>
              ))}
            </List>
          </Stack>
        </Paper>
      )}

      <Paper withBorder p="md" radius="md">
        <Stack gap={4}>
          <Title order={5}>The numbers</Title>
          <Text size="sm">
            Score covers {facts.score_coverage_pct.toFixed(0)}% of the story, ambience beds{" "}
            {facts.bed_coverage_pct.toFixed(0)}%.
            {facts.longest_without_score
              ? ` The longest stretch without score is ${formatSeconds(
                  facts.longest_without_score.length_s,
                )} (${formatSeconds(facts.longest_without_score.start_s)} to ${formatSeconds(
                  facts.longest_without_score.end_s,
                )}).`
              : ""}
          </Text>
          <Text size="sm">
            {Object.entries(facts.counts)
              .map(([kind, count]) => `${count} ${(KIND_LABELS[kind] ?? kind).toLowerCase()}`)
              .join(", ") || "No cues"}
            {facts.silences.length > 0
              ? `. Silences: ${facts.silences
                  .map((item) => `${formatSeconds(item.start_s)} to ${formatSeconds(item.end_s)}`)
                  .join(", ")}`
              : ""}
            .
          </Text>
          {facts.rerouted.length > 0 && (
            <Text size="sm" c="orange">
              Made by Stable Audio 3 instead of H3: {facts.rerouted.join(", ")}.
            </Text>
          )}
        </Stack>
      </Paper>

      {plan.rounds.length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            <Title order={5}>What the critics said</Title>
            {plan.rounds.map((round) => (
              <Stack key={round.round} gap={4}>
                <Group gap="xs">
                  <Text size="sm" fw={600}>
                    {round.critiques.length === 1 && round.critiques[0].lens === "cue_detail"
                      ? "Revision from the cues"
                      : `Round ${round.round}`}
                  </Text>
                  <Badge size="sm" variant="light" color={round.revised ? "blue" : "gray"}>
                    {round.revised ? "Revised" : "Not revised"}
                  </Badge>
                </Group>
                {round.failure && (
                  <Text size="xs" c="orange">
                    The reviser failed, the earlier plan was kept: {round.failure}
                  </Text>
                )}
                {round.critiques.map((critique) => (
                  <Stack key={critique.lens} gap={2}>
                    <Group gap="xs">
                      <Text size="sm">{LENS_LABELS[critique.lens] ?? critique.lens}</Text>
                      <Badge
                        size="sm"
                        variant="light"
                        color={
                          critique.verdict === "ok"
                            ? "green"
                            : critique.verdict === "change"
                              ? "yellow"
                              : "red"
                        }
                      >
                        {critique.verdict === "ok"
                          ? "Fine"
                          : critique.verdict === "change"
                            ? "Changes asked"
                            : "Failed"}
                      </Badge>
                    </Group>
                    {critique.failure && (
                      <Text size="xs" c="orange">
                        {critique.failure}
                      </Text>
                    )}
                    {critique.notes.length > 0 && (
                      <List size="xs">
                        {critique.notes.map((note, index) => (
                          <List.Item key={index}>
                            <b>{note.target}:</b> {note.problem} {note.suggestion}
                          </List.Item>
                        ))}
                      </List>
                    )}
                  </Stack>
                ))}
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}

/** "cue_2  Score  ACE-Step  0:10 to 0:42  a quiet piano line under the opening". */
function CueLine({ cue }: { cue: MusicPlanCue }) {
  return (
    <Group gap="xs" wrap="nowrap" align="flex-start">
      <Badge size="sm" variant="light" color={KIND_COLORS[cue.kind] ?? "gray"}>
        {KIND_LABELS[cue.kind] ?? cue.kind}
      </Badge>
      <Text size="sm">
        <b>{cue.id}</b>
        {cue.maker ? ` (${MAKER_LABELS[cue.maker] ?? cue.maker})` : ""}, {cueTimes(cue)}:{" "}
        {cue.summary}
        {cue.emotion ? ` Feels ${cue.emotion}.` : ""} Intensity {cue.intensity}.
      </Text>
    </Group>
  );
}

/** Where the cue's anchors sit, in words, and how it starts and ends. */
function anchorLines(cue: MusicPlanCue, timeline: MusicPlanOut["timeline"]): string {
  const parts: string[] = [];
  if (cue.at) parts.push(`At ${describeAnchor(timeline, cue.at)}.`);
  if (cue.start) parts.push(`Starts ${describeAnchor(timeline, cue.start)}.`);
  if (cue.end) parts.push(`Ends ${describeAnchor(timeline, cue.end)}.`);
  if (cue.start_style)
    parts.push(`Start: ${START_STYLE_LABELS[cue.start_style] ?? cue.start_style}.`);
  if (cue.end_style) parts.push(`End: ${END_STYLE_LABELS[cue.end_style] ?? cue.end_style}.`);
  return parts.join(" ");
}
