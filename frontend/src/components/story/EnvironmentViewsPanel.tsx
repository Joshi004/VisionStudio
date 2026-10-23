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
import {
  useEnvironmentViews,
  useMakeViewPictures,
  usePlanAllEnvironmentViews,
  usePlanEnvironmentViews,
  useRemakeProjectView,
  type EnvironmentViewsEntry,
} from "../../api/environmentViews";
import { EnvironmentViewCard } from "../environmentLab/EnvironmentViewCard";
import { JobStatusBadge } from "../jobs/JobStatusBadge";

type EnvironmentViewsPanelProps = {
  projectId: number;
};

const STATUS: Record<EnvironmentViewsEntry["status"], { label: string; color: string }> = {
  not_planned: { label: "Not planned", color: "gray" },
  planned: { label: "Planned", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

type EntryRowProps = {
  entry: EnvironmentViewsEntry;
  projectId: number;
  busy: boolean;
  onPlan: () => void;
};

/** One environment: its view plan, which views cover which scene, and the views' pictures. */
function EntryRow({ entry, projectId, busy, onPlan }: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const makePictures = useMakeViewPictures(projectId);
  const remake = useRemakeProjectView(projectId);
  const job = entry.job;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
  const planned = entry.status !== "not_planned";
  const reason = active ? null : entry.plan_blocked_reason;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {entry.name}
            </Text>
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
            {entry.version !== null && (
              <Badge variant="light" style={{ cursor: "default" }}>
                plan v{entry.version.version}
              </Badge>
            )}
            {planned && (
              <Badge
                variant="light"
                color={entry.pictures_status === "ready" ? "green" : "gray"}
              >
                pictures: {entry.pictures_status.replace("_", " ")}
              </Badge>
            )}
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          </Group>
          <Text size="xs" c="dimmed">
            Scenes: {entry.scenes.join(", ")}
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
          {planned && (
            <Button size="compact-xs" variant="default" onClick={() => setOpen((value) => !value)}>
              {open ? "Hide the views" : "Show the views"}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!entry.can_plan || busy}
            onClick={onPlan}
          >
            {planned ? "Re-plan" : "Plan the views"}
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            loading={makePictures.isPending}
            disabled={!entry.can_make_pictures || busy}
            onClick={() => makePictures.mutate(entry.id)}
          >
            Make pictures
          </Button>
        </Group>
      </Group>
      {makePictures.isError && (
        <Alert color="red" p="xs" title="Could not start the pictures">
          {describeError(makePictures.error)}
        </Alert>
      )}
      {remake.isError && (
        <Alert color="red" p="xs" title="Could not start the picture">
          {describeError(remake.error)}
        </Alert>
      )}
      <Collapse expanded={open}>
        <Stack gap="sm" pl="sm">
          {entry.master !== null && (
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Establishing view (the canonical picture)
              </Text>
              <img
                src={entry.master.url}
                alt={`${entry.name}, canonical picture`}
                loading="lazy"
                style={{
                  width: "100%",
                  maxWidth: 420,
                  aspectRatio: "16 / 9",
                  objectFit: "cover",
                  borderRadius: 4,
                  display: "block",
                }}
              />
            </Stack>
          )}
          {entry.coverage.map((scene) => (
            <Text key={scene.scene_id} size="xs" c="dimmed">
              {scene.title}:{" "}
              {Object.entries(scene.by_side)
                .map(([side, ids]) => `behind a character on the ${side}: ${ids.join(", ")}`)
                .join("; ")}
              {scene.group.length > 0 ? `; the group: ${scene.group.join(", ")}` : ""}
            </Text>
          ))}
          {entry.views.map((view) => (
            <EnvironmentViewCard
              key={view.id}
              view={view}
              onRemake={() => remake.mutate(view.id)}
              remaking={remake.isPending && remake.variables === view.id}
            />
          ))}
        </Stack>
      </Collapse>
    </Stack>
  );
}

/**
 * The Environment Views stage: once every scene is staged, one model call per place plans which
 * views of it the scenes need, and each view is made by editing the place's canonical picture, so
 * two characters in one room are not put in front of the same wall. **Plan all** covers every
 * place whose plan is missing or out of date; **Make pictures** draws the views of one plan.
 */
export function EnvironmentViewsPanel({ projectId }: EnvironmentViewsPanelProps) {
  const { data, isLoading, isError, error } = useEnvironmentViews(projectId);
  const planAll = usePlanAllEnvironmentViews(projectId);
  const planOne = usePlanEnvironmentViews(projectId);

  const busy = planAll.isPending || planOne.isPending;
  const entries = data?.entries ?? [];
  const blocked = (data?.blocked_reason ?? null) !== null && entries.length === 0;
  const allCount = entries.filter((entry) => entry.can_plan && entry.status !== "planned").length;
  const skipped = planAll.data?.skipped ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Environment views</Title>
            <Text size="sm" c="dimmed">
              Draws each place from the directions its scenes need, as edits of its canonical
              picture, so a character with the stove behind them and one with the window behind
              them do not share a wall.
            </Text>
          </Stack>
          <Button
            onClick={() => planAll.mutate()}
            loading={planAll.isPending}
            disabled={isLoading || isError || busy || blocked || allCount === 0}
          >
            Plan all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the environment views">
            {describeError(error)}
          </Alert>
        )}
        {planAll.isError && (
          <Alert color="red" title="Could not start the view planning">
            {describeError(planAll.error)}
          </Alert>
        )}
        {planOne.isError && (
          <Alert color="red" title="Could not start the view planning">
            {describeError(planOne.error)}
          </Alert>
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not started">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={item.id} size="sm">
                  {item.name}: {item.reason}
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
            projectId={projectId}
            busy={busy}
            onPlan={() => planOne.mutate(entry.id)}
          />
        ))}
      </Stack>
    </Paper>
  );
}
