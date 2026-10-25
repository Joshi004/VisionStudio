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
  useMusicPlacement,
  useMusicPlacementVersion,
  useRunMusicPlacement,
  type MusicPlacementOut,
  type PlacedSound,
  type PlacementEdge,
} from "../../api/musicPlacement";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { MusicPlacementStrip } from "./MusicPlacementStrip";
import {
  JOIN_LABELS,
  KIND_COLORS,
  KIND_LABELS,
  formatSeconds,
} from "./musicPlanView";

type MusicPlacementPanelProps = {
  projectId: number;
};

const LADDER_LABELS = [
  "found in the window",
  "found after widening the window",
  "a gentler technique",
  "covered by a sound that already exists",
  "chosen by the model",
  "flagged",
];

const CHOSEN_BY_LABELS: Record<string, string> = {
  code: "code",
  model: "the model",
};

function exact(seconds: number): string {
  return `${seconds.toFixed(2)} s`;
}

/**
 * The music placement stage: where every selected music take sits on the finished video's
 * timeline, with its fades, its joins and every fallback that was needed. Run / Re-run places the
 * music again. Nothing here is edited by hand. When music is switched off, the panel only says so.
 */
export function MusicPlacementPanel({ projectId }: MusicPlacementPanelProps) {
  const { data, isLoading, isError, error } = useMusicPlacement(projectId);
  const run = useRunMusicPlacement(projectId);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useMusicPlacementVersion(
    projectId,
    viewingOlder ? shownVersion : null,
  );
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);
  const musicOff = data !== undefined && !data.music_enabled;
  const blocked = data?.blocked_reason ?? null;
  const nothing = data?.nothing_to_place ?? false;

  const startRun = () => {
    // A new version is on its way: show it when it arrives.
    setPicked(null);
    run.mutate();
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Music placement</Title>
              <Text size="sm" c="dimmed">
                The exact second of every music take on the finished video:
                where each one starts and stops, its fades, how one cue meets
                the next, and what was done where nothing fitted.
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
                  onChange={(value) =>
                    value !== null && setPicked(Number(value))
                  }
                />
              )}
              <Button
                onClick={startRun}
                loading={run.isPending || active}
                disabled={
                  isLoading ||
                  isError ||
                  musicOff ||
                  nothing ||
                  blocked !== null
                }
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
          {!musicOff && nothing && (
            <Text size="sm" c="dimmed">
              No cue of the plan needs a recording, so there is nothing to
              place.
            </Text>
          )}
          {musicOff && (
            <Alert color="gray" title="Music is switched off">
              This project is made without music, so this step is skipped. Turn
              music on in the{" "}
              <Link to={`/projects/${projectId}/settings`}>
                project settings
              </Link>{" "}
              to place it.
            </Alert>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the music placement">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the music placement">
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
                  Something this placement was made from has changed. Press
                  Re-run to place the music again.
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

      {shown && <MusicPlacementView placement={shown} />}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}
    </Stack>
  );
}

/** The placement over the time strip, then what was checked and every fallback. */
function MusicPlacementView({ placement }: { placement: MusicPlacementOut }) {
  const { content } = placement;
  const { facts } = content;
  const inside = facts.inside_speech;
  const withFallbacks = content.placements.filter(
    (item) => item.fallbacks.length > 0,
  );

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group gap="sm">
            <Title order={5}>The placement</Title>
            <Text size="xs" c="dimmed">
              Version {placement.version}, {content.placements.length} sounds
              placed on {formatSeconds(content.timeline.total_s)} of story
            </Text>
          </Group>
          <MusicPlacementStrip content={content} />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap={4}>
          <Title order={5}>What was checked</Title>
          {inside.length === 0 ? (
            <Text size="sm" c="green">
              No music starts or stops inside a spoken word.
            </Text>
          ) : (
            <>
              <Text size="sm" c="orange">
                These points could not be kept out of a spoken word:
              </Text>
              <List size="sm">
                {inside.map((item) => (
                  <List.Item key={`${item.cue_id}-${item.edge}`}>
                    The {item.edge === "end" ? "stop" : "start"} of{" "}
                    {item.cue_id} at {exact(item.second)}
                    {item.flagged ? " (flagged)" : ""}.
                  </List.Item>
                ))}
              </List>
            </>
          )}
          {facts.unmeasured.length > 0 && (
            <Text size="sm" c="orange">
              These could not be measured, so the planned seconds were used:{" "}
              {facts.unmeasured.join(", ")}.
            </Text>
          )}
          {facts.model_asked > 0 && (
            <Text size="sm" c={facts.model_failed ? "orange" : undefined}>
              The model was asked to choose among real moments for{" "}
              {facts.model_asked} point
              {facts.model_asked === 1 ? "" : "s"}
              {facts.model_failed
                ? `, but could not answer: ${facts.model_failed}`
                : "."}
            </Text>
          )}
        </Stack>
      </Paper>

      {content.flags.length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Stack gap={4}>
            <Title order={5}>Flagged for you</Title>
            <List size="sm">
              {content.flags.map((flag, index) => (
                <List.Item key={index}>
                  <Text size="sm" c="orange" span>
                    {flag.message}
                  </Text>
                </List.Item>
              ))}
            </List>
          </Stack>
        </Paper>
      )}

      <Paper withBorder p="md" radius="md">
        <Stack gap="xs">
          <Title order={5}>Every sound</Title>
          {content.placements.length === 0 && (
            <Text size="sm" c="dimmed">
              Nothing was placed.
            </Text>
          )}
          {content.placements.map((item) => (
            <PlacedLine
              key={item.item_id}
              item={item}
              rate={content.sample_rate}
            />
          ))}
        </Stack>
      </Paper>

      {content.joins.length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Stack gap={4}>
            <Title order={5}>Joins</Title>
            <List size="sm">
              {content.joins.map((join) => (
                <List.Item key={`${join.from_cue}-${join.to_cue}`}>
                  {join.from_cue} to {join.to_cue}: a{" "}
                  {JOIN_LABELS[join.type] ?? join.type} at {exact(join.point_s)}
                  , {exact(join.length_s)} long
                  {join.made_as !== join.type
                    ? `, made as a ${JOIN_LABELS[join.made_as] ?? join.made_as}`
                    : ""}
                  .{join.notes.length > 0 ? ` ${join.notes.join(" ")}` : ""}
                </List.Item>
              ))}
            </List>
          </Stack>
        </Paper>
      )}

      {withFallbacks.length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Stack gap={4}>
            <Title order={5}>Where it was not straightforward</Title>
            {withFallbacks.map((item) => (
              <Stack key={item.item_id} gap={0}>
                <Text size="sm" fw={600}>
                  {item.cue_id}: {item.summary}
                </Text>
                <List size="xs">
                  {item.fallbacks.map((note, index) => (
                    <List.Item key={index}>{note}</List.Item>
                  ))}
                </List>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      {content.choices.length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Stack gap={4}>
            <Title order={5}>What the model chose</Title>
            <List size="sm">
              {content.choices.map((choice) => (
                <List.Item key={choice.id}>
                  {choice.cue_id},{" "}
                  {choice.edge === "at" ? "the sound" : `the ${choice.edge}`}:{" "}
                  {choice.picked}
                  {choice.reason ? ` (${choice.reason})` : ""}
                </List.Item>
              ))}
            </List>
          </Stack>
        </Paper>
      )}

      {(content.h3_sounds.length > 0 || content.mix_requests.length > 0) && (
        <Paper withBorder p="md" radius="md">
          <Stack gap={4}>
            <Title order={5}>For the mix</Title>
            {content.h3_sounds.length > 0 && (
              <>
                <Text size="sm">Sounds H3 makes, found at:</Text>
                <List size="sm">
                  {content.h3_sounds.map((sound) => (
                    <List.Item key={sound.cue_id}>
                      {sound.cue_id} at {exact(sound.chosen_s)}:{" "}
                      {sound.description}
                    </List.Item>
                  ))}
                </List>
              </>
            )}
            {content.mix_requests.length > 0 && (
              <>
                <Text size="sm">
                  Swells of an ambience bed that hide a start or a stop:
                </Text>
                <List size="sm">
                  {content.mix_requests.map((request, index) => (
                    <List.Item key={index}>
                      {request.cue_id} at {exact(request.second)},{" "}
                      {exact(request.length_s)}: {request.reason}
                    </List.Item>
                  ))}
                </List>
              </>
            )}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}

/** "cue_2  Score  0:10.00 to 0:42.50: a quiet piano line", then how each edge was found. */
function PlacedLine({ item, rate }: { item: PlacedSound; rate: number }) {
  const start = item.story_start_sample / rate;
  const end = start + item.length_samples / rate;
  return (
    <Stack gap={2}>
      <Group gap="xs" wrap="nowrap" align="flex-start">
        <Badge
          size="sm"
          variant="light"
          color={KIND_COLORS[item.kind] ?? "gray"}
        >
          {KIND_LABELS[item.kind] ?? item.kind}
        </Badge>
        <Text size="sm">
          <b>{item.item_id}</b>,{" "}
          {item.moment
            ? `lands at ${exact(item.moment.chosen_s)}`
            : `${exact(start)} to ${exact(end)}`}
          : {item.summary}
        </Text>
      </Group>
      {item.start && <EdgeLine label="Starts" edge={item.start} />}
      {item.end && <EdgeLine label="Stops" edge={item.end} />}
      {item.moment && (
        <Text size="xs" c="dimmed">
          Lands on {item.moment.description} (
          {LADDER_LABELS[item.moment.ladder_step] ?? "found"}, by{" "}
          {CHOSEN_BY_LABELS[item.moment.chosen_by] ?? item.moment.chosen_by}).
        </Text>
      )}
      {(item.join_in || item.join_out) && (
        <Text size="xs" c="dimmed">
          {item.join_in
            ? `Comes in from ${item.join_in.cue_id} (${JOIN_LABELS[item.join_in.type] ?? item.join_in.type}). `
            : ""}
          {item.join_out
            ? `Goes out into ${item.join_out.cue_id} (${JOIN_LABELS[item.join_out.type] ?? item.join_out.type}).`
            : ""}
        </Text>
      )}
      {item.slide_s !== 0 && (
        <Text size="xs" c="dimmed">
          Moved {exact(Math.abs(item.slide_s))}{" "}
          {item.slide_s > 0 ? "later" : "earlier"} to line up with the planned
          change of mood.
        </Text>
      )}
      {item.notes.map((note) => (
        <Text key={note} size="xs" c="orange">
          {note}
        </Text>
      ))}
    </Stack>
  );
}

function EdgeLine({ label, edge }: { label: string; edge: PlacementEdge }) {
  return (
    <Text size="xs" c={edge.flagged ? "red" : "dimmed"}>
      {label} at {exact(edge.chosen_s)} (planned {exact(edge.nominal_s)}):{" "}
      {edge.description}, {LADDER_LABELS[edge.ladder_step] ?? "found"}
      {edge.chosen_by === "model" ? ", chosen by the model" : ""}.
    </Text>
  );
}
