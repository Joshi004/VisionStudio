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
import {
  usePlanAllSpeechUnits,
  usePlanOneSceneSpeechUnits,
  totalSeconds,
  useSpeechUnits,
  type SpeechUnitsEntry,
} from "../../api/speechUnits";
import { ArtifactViewer } from "./ArtifactViewer";
import { SpeechUnitsView } from "./SpeechUnitsView";

type SpeechUnitsPanelProps = {
  projectId: number;
};

const STATUS: Record<
  SpeechUnitsEntry["status"],
  { label: string; color: string }
> = {
  not_planned: { label: "Not planned", color: "gray" },
  planned: { label: "Planned", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

type EntryRowProps = {
  entry: SpeechUnitsEntry;
  characterNames: Record<string, string>;
  /** True when nothing can be planned yet; the reason is shown once, above the list. */
  projectBlocked: boolean;
  busy: boolean;
  onPlan: () => void;
};

/**
 * One scene: its status, why its plan is out of date, and the speech units themselves, read
 * only.
 */
function EntryRow({
  entry,
  characterNames,
  projectBlocked,
  busy,
  onPlan,
}: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const status = STATUS[entry.status];
  const planned = entry.status === "planned" || entry.status === "out_of_date";
  // Why this one scene cannot be planned, when that is about the scene itself.
  const reason = projectBlocked ? null : entry.blocked_reason;

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
                title="The newest version of this scene's speech units"
              >
                v{entry.version.version}
              </Badge>
            )}
            {entry.units !== null && (
              <Badge variant="light" color="gray">
                {entry.units.units.length} units, about{" "}
                {totalSeconds(entry.units).toFixed(1)} s
              </Badge>
            )}
            {entry.units !== null && entry.units.warnings.length > 0 && (
              <Badge
                variant="light"
                color="yellow"
                title="Pieces that are over their limit and could not be cut any further"
              >
                {entry.units.warnings.length} over the limit
              </Badge>
            )}
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
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.units !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the units" : "Show the units"}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            disabled={!entry.can_run || busy}
            onClick={onPlan}
          >
            {planned ? "Plan again" : "Plan"}
          </Button>
        </Group>
      </Group>
      {entry.units !== null && entry.version !== null && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title="Speech units"
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <SpeechUnitsView
              units={entry.units}
              characterNames={characterNames}
            />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

/**
 * The Speech Planning stage: each scene's narration and dialogue events are cut into speech
 * units with an estimated length. It is plain code, so planning is instant and uses no model. A
 * scene can only be planned once its events are extracted. **Plan all** covers every scene whose
 * units are missing or out of date.
 */
export function SpeechUnitsPanel({ projectId }: SpeechUnitsPanelProps) {
  const { data, isLoading, isError, error } = useSpeechUnits(projectId);
  const planAll = usePlanAllSpeechUnits(projectId);
  const planOne = usePlanOneSceneSpeechUnits(projectId);

  const busy = planAll.isPending || planOne.isPending;
  const entries = data?.entries ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  const characterNames = Object.fromEntries(
    (data?.characters ?? []).map((character) => [character.id, character.name]),
  );
  // What "Plan all" would do: the scenes that may run and are not planned and current.
  const allCount = entries.filter(
    (entry) => entry.can_run && entry.status !== "planned",
  ).length;
  const skipped = planAll.data?.skipped ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Speech units</Title>
            <Text size="sm" c="dimmed">
              Cuts each scene&apos;s narration and dialogue into units that can
              each be turned into speech, with an estimated length. Long
              narration is cut at sentences and clauses; dialogue only when it
              would not fit one shot. The pace and the limits are in Settings,
              under Speech.
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
          <Alert color="red" title="Could not load the speech units">
            {describeError(error)}
          </Alert>
        )}
        {planAll.isError && (
          <Alert color="red" title="Could not plan the speech units">
            {describeError(planAll.error)}
          </Alert>
        )}
        {planOne.isError && (
          <Alert color="red" title="Could not plan the speech units">
            {describeError(planOne.error)}
          </Alert>
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not planned">
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
