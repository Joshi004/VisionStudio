import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { useSceneEvents } from "../../api/sceneEvents";
import type { SceneEventsContent } from "../../api/sceneEvents";
import { useSpeechAudio } from "../../api/speechAudio";
import type { SpeechUnitAudio } from "../../api/speechAudio";
import { useSpeechUnits } from "../../api/speechUnits";
import type { SpeechUnitsContent } from "../../api/speechUnits";
import {
  usePlanAllShots,
  usePlanOneSceneShots,
  useSaveShotPlan,
  useShotPlans,
  type ShotPlanEntry,
  type ShotPlanInput,
} from "../../api/shotPlans";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { FeedbackBadge } from "./FeedbackBadge";
import { FeedbackModal } from "./FeedbackModal";
import { PromptHoverCard } from "./PromptHoverCard";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { SceneTimelineView } from "./SceneTimelineView";
import { ShotPlanEditor } from "./ShotPlanEditor";
import { ShotPlanView } from "./ShotPlanView";

type ShotPlansPanelProps = {
  projectId: number;
};

/** What the timeline of a scene's newest plan says, as a badge. Nothing for a scene with no plan. */
function timelineBadge(entry: ShotPlanEntry): {
  label: string;
  color: string;
} | null {
  const timeline = entry.timeline;
  if (timeline === null) {
    return null;
  }
  const blocking = timeline.problems.filter(
    (problem) => problem.severity === "blocking",
  ).length;
  const flagged = timeline.problems.length - blocking;
  if (blocking > 0) {
    return { label: "Timeline blocked", color: "red" };
  }
  if (flagged > 0) {
    return {
      label:
        flagged === 1 ? "Timeline: 1 warning" : `Timeline: ${flagged} warnings`,
      color: "yellow",
    };
  }
  return { label: "Timeline OK", color: "green" };
}

const STATUS: Record<
  ShotPlanEntry["status"],
  { label: string; color: string }
> = {
  not_planned: { label: "Not planned", color: "gray" },
  planned: { label: "Planned", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

type EntryRowProps = {
  entry: ShotPlanEntry;
  events: SceneEventsContent | null;
  units: SpeechUnitsContent | null;
  audio: SpeechUnitAudio[];
  characterNames: Record<string, string>;
  /** True when nothing can be planned yet; the reason is shown once, above the list. */
  projectBlocked: boolean;
  /** How many automatic re-plans a scene gets (Settings, Shot duration). */
  replanMaxTries: number;
  busy: boolean;
  onPlan: () => void;
  onFeedback: () => void;
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (plan: ShotPlanInput, done: () => void) => void;
};

/**
 * One scene: its status, why its plan is out of date, the job's failure when the last run
 * failed, and the shots themselves, which can be edited by hand.
 */
function EntryRow({
  entry,
  events,
  units,
  audio,
  characterNames,
  projectBlocked,
  replanMaxTries,
  busy,
  onPlan,
  onFeedback,
  saving,
  saveError,
  onStartEdit,
  onSave,
}: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const job = entry.job;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
  const timeline = timelineBadge(entry);
  const replanning = active && entry.replan_attempt > 0;
  // The tries are used up and the plan still has problems.
  const triesUsed =
    !active &&
    entry.timeline !== null &&
    entry.timeline.problems.length > 0 &&
    entry.replan_attempt >= replanMaxTries;
  const planned = entry.status === "planned" || entry.status === "out_of_date";
  // Why this one scene cannot be planned, when that is about the scene itself.
  const reason = projectBlocked || active ? null : entry.blocked_reason;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={40}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {entry.index}
        </Badge>
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {entry.title}
            </Text>
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
            {entry.version !== null && (
              <PromptHoverCard jobId={entry.version.job_id} source={entry.version.source}>
                <Badge variant="light" style={{ cursor: "help" }}>
                  v{entry.version.version}
                </Badge>
              </PromptHoverCard>
            )}
            <FeedbackBadge text={entry.version?.feedback} />
            {entry.shots !== null && entry.total_seconds !== null && (
              <Badge variant="light" color="gray">
                {entry.shots.shots.length} shots,{" "}
                {entry.total_seconds.toFixed(1)} s
              </Badge>
            )}
            {timeline !== null && (
              <Badge
                variant="light"
                color={timeline.color}
                title={entry.generation_blocked_reason ?? undefined}
              >
                {timeline.label}
              </Badge>
            )}
            {replanning && (
              <Badge variant="light" color="blue">
                Re-planning (try {entry.replan_attempt} of {replanMaxTries})
              </Badge>
            )}
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          </Group>
          <Text size="sm" c="dimmed">
            {entry.description}
          </Text>
          {reason !== null && (
            <Text size="xs" c="dimmed">
              {reason}
            </Text>
          )}
          {entry.reasons.map((text) => (
            <Text key={text} size="xs" c="yellow.8">
              {text}
            </Text>
          ))}
          {triesUsed && (
            <Text size="xs" c="dimmed">
              {replanMaxTries === 0
                ? "Automatic re-planning is off."
                : `The ${replanMaxTries} automatic re-plans are used.`}{" "}
              {entry.generation_ready
                ? "The remaining problems are warnings: generation may use these shots."
                : "Generation stays blocked for this scene until the shots are planned again."}
            </Text>
          )}
          {job?.status === "failed" && (
            <Alert color="red" p="xs" title="The last planning failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" justify="flex-end" maw={420} style={{ flexShrink: 0 }}>
          {entry.timeline !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setTimelineOpen((value) => !value)}
            >
              {timelineOpen ? "Hide the timeline" : "Show the timeline"}
            </Button>
          )}
          {entry.shots !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the shots" : "Show the shots"}
            </Button>
          )}
          {entry.shots !== null && (
            <Button
              size="compact-sm"
              variant="default"
              disabled={editing || active || busy}
              onClick={() => {
                onStartEdit();
                setOpen(false);
                setEditing(true);
              }}
            >
              Edit
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy || editing}
            onClick={onPlan}
          >
            {planned ? "Plan again" : "Plan"}
          </Button>
          {entry.shots !== null && (
            <Button
              size="compact-sm"
              variant="default"
              title="Plan this scene again, with a note from you for the model"
              disabled={!entry.can_run || busy || editing}
              onClick={onFeedback}
            >
              Regenerate with feedback
            </Button>
          )}
        </Group>
      </Group>
      {editing && entry.shots !== null && (
        <Paper withBorder p="md" radius="sm" ml={48}>
          <ShotPlanEditor
            initial={entry.shots}
            events={events}
            units={units}
            characterNames={characterNames}
            saving={saving}
            error={saveError}
            onSave={(plan) => onSave(plan, () => setEditing(false))}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {entry.timeline !== null && (
        <Collapse expanded={timelineOpen}>
          <SceneTimelineView
            timeline={entry.timeline}
            storyStartSeconds={entry.story_start_seconds}
          />
        </Collapse>
      )}
      {entry.shots !== null && entry.version !== null && !editing && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title="Shots"
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <ShotPlanView
              plan={entry.shots}
              events={events}
              units={units}
              audio={audio}
              characterNames={characterNames}
            />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

/**
 * The Shot Planning stage: one model call per scene decides how the audience sees its events,
 * as a list of shots with their target lengths and the speech each one carries. A scene can
 * only be planned once the speech of every unit is made, because the plan is built on the
 * measured lengths. **Plan all** covers every such scene whose plan is missing or out of date.
 */
export function ShotPlansPanel({ projectId }: ShotPlansPanelProps) {
  const { data, isLoading, isError, error } = useShotPlans(projectId);
  const planAll = usePlanAllShots(projectId);
  const planOne = usePlanOneSceneShots(projectId);
  const save = useSaveShotPlan(projectId);
  // The scene whose newest plan the user wrote, waiting for "yes, plan it again".
  const [confirming, setConfirming] = useState<ShotPlanEntry | null>(null);
  // The scene the user is writing a note about.
  const [feedbackFor, setFeedbackFor] = useState<ShotPlanEntry | null>(null);
  // What a shot names (events, units and their measured length) comes from the earlier
  // stages. They are already loaded for their own panels, so this shares their queries.
  const sceneEvents = useSceneEvents(projectId).data;
  const speechUnits = useSpeechUnits(projectId).data;
  const speechAudio = useSpeechAudio(projectId).data;

  const busy = planAll.isPending || planOne.isPending;
  const entries = data?.entries ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  const characterNames = Object.fromEntries(
    (sceneEvents?.characters ?? []).map((character) => [
      character.id,
      character.name,
    ]),
  );
  // What "Plan all" would start: the scenes that may run and are not planned and current.
  const allCount = entries.filter(
    (entry) => entry.can_run && entry.status !== "planned",
  ).length;
  const skipped = planAll.data?.skipped ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Shot plans</Title>
            <Text size="sm" c="dimmed">
              Decides how the audience sees each scene: a list of shots, each
              with the events it shows, the speech heard during it and a target
              length. It uses the measured length of the speech, so every unit
              must be spoken first.
              {data?.target_min_seconds != null &&
                data.target_max_seconds != null &&
                ` Shots are asked to stay between ${data.target_min_seconds} and ${data.target_max_seconds} s. A scene whose timeline has a problem is planned again by itself, up to ${data.replan_max_tries} times.`}
            </Text>
          </Stack>
          <Button
            onClick={() => planAll.mutate()}
            loading={planAll.isPending}
            disabled={
              isLoading || isError || busy || projectBlocked || allCount === 0
            }
          >
            Plan all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the shot plans">
            {describeError(error)}
          </Alert>
        )}
        {planAll.isError && (
          <Alert color="red" title="Could not start the shot planning">
            {describeError(planAll.error)}
          </Alert>
        )}
        {planOne.isError && (
          <Alert color="red" title="Could not start the shot planning">
            {describeError(planOne.error)}
          </Alert>
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not started">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={item.scene_id} size="sm">
                  {item.title}: {item.reason}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        {data && data.blocked_reason !== null && (
          <Text size="sm" c="dimmed">
            {data.blocked_reason}
          </Text>
        )}
        {entries.length > 0 && <Divider />}

        {entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            events={
              sceneEvents?.entries.find((item) => item.id === entry.id)
                ?.events ?? null
            }
            units={
              speechUnits?.entries.find((item) => item.id === entry.id)
                ?.units ?? null
            }
            audio={
              speechAudio?.scenes.find((item) => item.scene_id === entry.id)
                ?.units ?? []
            }
            characterNames={characterNames}
            projectBlocked={projectBlocked}
            replanMaxTries={data?.replan_max_tries ?? 0}
            busy={busy}
            onPlan={() =>
              entry.needs_confirmation
                ? setConfirming(entry)
                : planOne.mutate({ sceneId: entry.id, confirmReplaceManual: false })
            }
            onFeedback={() => setFeedbackFor(entry)}
            saving={save.isPending}
            saveError={save.error}
            onStartEdit={() => save.reset()}
            onSave={(plan, done) =>
              save.mutate({ sceneId: entry.id, plan }, { onSuccess: done })
            }
          />
        ))}
      </Stack>
      <FeedbackModal
        opened={feedbackFor !== null}
        title={`Feedback on the shot plan of ${feedbackFor?.title ?? "this scene"}`}
        what="the shot plan of this scene"
        initialText={feedbackFor?.version?.feedback ?? ""}
        writtenByUser={feedbackFor?.needs_confirmation ?? false}
        submitLabel="Plan with feedback"
        onCancel={() => setFeedbackFor(null)}
        onSubmit={(text) => {
          if (feedbackFor !== null) {
            planOne.mutate({
              sceneId: feedbackFor.id,
              confirmReplaceManual: feedbackFor.needs_confirmation,
              feedback: text,
            });
          }
          setFeedbackFor(null);
        }}
      />
      <ReplaceManualModal
        opened={confirming !== null}
        title="Plan this scene again?"
        what={`The newest shot plan of ${confirming?.title ?? "this scene"}`}
        confirmLabel="Plan again"
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming !== null) {
            planOne.mutate({ sceneId: confirming.id, confirmReplaceManual: true });
          }
          setConfirming(null);
        }}
      />
    </Paper>
  );
}
