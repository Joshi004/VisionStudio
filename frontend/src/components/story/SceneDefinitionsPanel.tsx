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
  useDefineAllScenes,
  useDefineOneScene,
  useSceneDefinitions,
  type SceneDefinitionEntry,
} from "../../api/sceneDefinitions";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { SceneDefinitionView } from "./SceneDefinitionView";

type SceneDefinitionsPanelProps = {
  projectId: number;
};

const STATUS: Record<
  SceneDefinitionEntry["status"],
  { label: string; color: string }
> = {
  not_defined: { label: "Not defined", color: "gray" },
  defined: { label: "Defined", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

type EntryRowProps = {
  entry: SceneDefinitionEntry;
  /** True when nothing can be defined yet; the reason is shown once, above the list. */
  projectBlocked: boolean;
  busy: boolean;
  onDefine: () => void;
};

/**
 * One scene: its status, why its definition is out of date, the job's failure when the last run
 * failed, and the definition itself, read only.
 */
function EntryRow({ entry, projectBlocked, busy, onDefine }: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const job = entry.job;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
  const defined = entry.status === "defined" || entry.status === "out_of_date";
  // Why this one scene cannot be defined, when that is about the scene itself.
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
                title="The newest version of this scene's definition"
              >
                v{entry.version.version}
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
            <Alert color="red" p="xs" title="The last definition failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.definition !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the definition" : "Show the definition"}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy}
            onClick={onDefine}
          >
            {defined ? "Re-define" : "Define"}
          </Button>
        </Group>
      </Group>
      {entry.definition !== null && entry.version !== null && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title="Definition"
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <SceneDefinitionView definition={entry.definition} />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

/**
 * The Scene Definition stage: one model call per scene writes its story context, where and when
 * it happens, who is in it, the mood, the dramatic goal and where each character starts and
 * ends. It can only run once every character and environment is defined, because each scene
 * chooses among them. **Define all** covers every scene that is not defined and up to date.
 */
export function SceneDefinitionsPanel({
  projectId,
}: SceneDefinitionsPanelProps) {
  const { data, isLoading, isError, error } = useSceneDefinitions(projectId);
  const defineAll = useDefineAllScenes(projectId);
  const defineOne = useDefineOneScene(projectId);

  const busy = defineAll.isPending || defineOne.isPending;
  const entries = data?.entries ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  // What "Define all" would start: the scenes that may run and are not defined and up to date.
  const allCount = entries.filter(
    (entry) => entry.can_run && entry.status !== "defined",
  ).length;
  const skipped = defineAll.data?.skipped ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Scene definitions</Title>
            <Text size="sm" c="dimmed">
              Writes each scene&apos;s context, place, time, characters, mood
              and goal. The place state and the looks it asks for are settled
              later.
            </Text>
          </Stack>
          <Button
            onClick={() => defineAll.mutate()}
            loading={defineAll.isPending}
            disabled={
              isLoading || isError || busy || projectBlocked || allCount === 0
            }
          >
            Define all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the scene definitions">
            {describeError(error)}
          </Alert>
        )}
        {defineAll.isError && (
          <Alert color="red" title="Could not start the scene definitions">
            {describeError(defineAll.error)}
          </Alert>
        )}
        {defineOne.isError && (
          <Alert color="red" title="Could not start the scene definition">
            {describeError(defineOne.error)}
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
            projectBlocked={projectBlocked}
            busy={busy}
            onDefine={() => defineOne.mutate(entry.id)}
          />
        ))}
      </Stack>
    </Paper>
  );
}
