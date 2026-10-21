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
  useShotPlans,
  type ShotPlanEntry,
} from "../../api/shotPlans";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { ShotPlanView } from "./ShotPlanView";

type ShotPlansPanelProps = {
  projectId: number;
};

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
  busy: boolean;
  onPlan: () => void;
};

/**
 * One scene: its status, why its plan is out of date, the job's failure when the last run
 * failed, and the shots themselves, read only.
 */
function EntryRow({
  entry,
  events,
  units,
  audio,
  characterNames,
  projectBlocked,
  busy,
  onPlan,
}: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const job = entry.job;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
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
              <Badge
                variant="light"
                title="The newest version of this scene's shot plan"
              >
                v{entry.version.version}
              </Badge>
            )}
            {entry.shots !== null && entry.total_seconds !== null && (
              <Badge variant="light" color="gray">
                {entry.shots.shots.length} shots, {entry.total_seconds.toFixed(1)}{" "}
                s
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
          {job?.status === "failed" && (
            <Alert color="red" p="xs" title="The last planning failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.shots !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the shots" : "Show the shots"}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy}
            onClick={onPlan}
          >
            {planned ? "Plan again" : "Plan"}
          </Button>
        </Group>
      </Group>
      {entry.shots !== null && entry.version !== null && (
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
                ` Shots are asked to stay between ${data.target_min_seconds} and ${data.target_max_seconds} s.`}
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
            busy={busy}
            onPlan={() => planOne.mutate(entry.id)}
          />
        ))}
      </Stack>
    </Paper>
  );
}
