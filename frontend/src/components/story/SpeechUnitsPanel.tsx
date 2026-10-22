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
  measuredSeconds,
  useMakeAllSpeech,
  useMakeOneSpeech,
  useSpeechAudio,
  type SpeechSceneAudio,
  type SpeechUnitAudio,
} from "../../api/speechAudio";
import {
  usePlanAllSpeechUnits,
  usePlanOneSceneSpeechUnits,
  totalSeconds,
  useSaveSpeechUnits,
  useSpeechUnits,
  type SpeechUnitInput,
  type SpeechUnitsEntry,
} from "../../api/speechUnits";
import { ArtifactViewer } from "./ArtifactViewer";
import { PromptHoverCard } from "./PromptHoverCard";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { SpeechUnitsEditor } from "./SpeechUnitsEditor";
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
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (units: SpeechUnitInput[], done: () => void) => void;
  /** Where the audio of this scene's units stands (PHASE-019). */
  sceneAudio: SpeechSceneAudio | undefined;
  speechBusy: boolean;
  onMake: (unitId: string) => void;
};

/**
 * One scene: its status, why its plan is out of date, and the speech units themselves, which
 * can be re-split by hand.
 */
function EntryRow({
  entry,
  characterNames,
  projectBlocked,
  busy,
  onPlan,
  saving,
  saveError,
  onStartEdit,
  onSave,
  sceneAudio,
  speechBusy,
  onMake,
}: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const status = STATUS[entry.status];
  const planned = entry.status === "planned" || entry.status === "out_of_date";
  // Why this one scene cannot be planned, when that is about the scene itself.
  const reason = projectBlocked ? null : entry.blocked_reason;
  const audioByUnit: Record<string, SpeechUnitAudio> = Object.fromEntries(
    (sceneAudio?.units ?? []).map((unit) => [unit.unit_id, unit]),
  );
  const made = (sceneAudio?.units ?? []).filter(
    (unit) => unit.audio !== null,
  ).length;

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
            {entry.units !== null && (
              <Badge variant="light" color="gray">
                {entry.units.units.length} units, about{" "}
                {totalSeconds(entry.units).toFixed(1)} s
              </Badge>
            )}
            {entry.units !== null && sceneAudio !== undefined && (
              <Badge
                variant="light"
                color={made === entry.units.units.length ? "green" : "gray"}
                title="Units with speech, and the measured length of that speech"
              >
                {made} of {entry.units.units.length} spoken
                {made > 0 &&
                  `, ${measuredSeconds(sceneAudio.units).toFixed(1)} s`}
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
          {entry.units !== null && (
            <Button
              size="compact-sm"
              variant="default"
              disabled={editing || busy}
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
            disabled={!entry.can_run || busy || editing}
            onClick={onPlan}
          >
            {planned ? "Plan again" : "Plan"}
          </Button>
        </Group>
      </Group>
      {editing && entry.units !== null && (
        <Paper withBorder p="md" radius="sm" ml={34}>
          <SpeechUnitsEditor
            initial={entry.units.units}
            characterNames={characterNames}
            saving={saving}
            error={saveError}
            onSave={(units) => onSave(units, () => setEditing(false))}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {entry.units !== null && entry.version !== null && !editing && (
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
              audio={audioByUnit}
              busy={speechBusy}
              onMake={onMake}
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
  const save = useSaveSpeechUnits(projectId);
  // The scene whose newest units the user cut, waiting for "yes, plan them again".
  const [confirming, setConfirming] = useState<SpeechUnitsEntry | null>(null);
  const audio = useSpeechAudio(projectId);
  const makeAll = useMakeAllSpeech(projectId);
  const makeOne = useMakeOneSpeech(projectId);

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

  const audioByScene = Object.fromEntries(
    (audio.data?.scenes ?? []).map((scene) => [scene.scene_id, scene]),
  );
  const speechBusy = makeAll.isPending || makeOne.isPending;
  // What "Make all" would do: the units that may run and have no current audio.
  const speechCount = (audio.data?.scenes ?? []).reduce(
    (sum, scene) =>
      sum +
      scene.units.filter(
        (unit) =>
          unit.can_run &&
          unit.status !== "ready" &&
          unit.status !== "in_progress",
      ).length,
    0,
  );
  // The units "Make all" left alone, one line for each reason.
  const leftAlone = new Map<string, number>();
  for (const item of makeAll.data?.skipped ?? []) {
    leftAlone.set(item.reason, (leftAlone.get(item.reason) ?? 0) + 1);
  }

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
              under Speech. Each unit can then be spoken in its character&apos;s
              saved voice (or the narrator&apos;s); the real length is measured
              from the speech.
            </Text>
          </Stack>
          <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
            <Button
              onClick={() => planAll.mutate()}
              loading={planAll.isPending}
              disabled={
                isLoading || isError || busy || projectBlocked || allCount === 0
              }
            >
              Plan all
            </Button>
            <Button
              variant="default"
              onClick={() => makeAll.mutate()}
              loading={makeAll.isPending}
              disabled={
                audio.isLoading ||
                audio.isError ||
                speechBusy ||
                projectBlocked ||
                speechCount === 0
              }
              title="Speak every unit that has no current speech, in its saved voice"
            >
              Make all speech
            </Button>
          </Group>
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
        {audio.isError && (
          <Alert color="red" title="Could not load the speech audio">
            {describeError(audio.error)}
          </Alert>
        )}
        {makeAll.isError && (
          <Alert color="red" title="Could not make the speech">
            {describeError(makeAll.error)}
          </Alert>
        )}
        {makeOne.isError && (
          <Alert color="red" title="Could not make the speech">
            {describeError(makeOne.error)}
          </Alert>
        )}
        {makeAll.data !== undefined && leftAlone.size > 0 && (
          <Alert
            color="blue"
            title={`Made ${makeAll.data.job_ids.length} speech${
              makeAll.data.job_ids.length === 1 ? "" : "es"
            }. Left alone:`}
          >
            <Stack gap={2}>
              {[...leftAlone.entries()].map(([reason, count]) => (
                <Text key={reason} size="sm">
                  {count} {count === 1 ? "unit" : "units"}: {reason}
                </Text>
              ))}
            </Stack>
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
            onPlan={() =>
              entry.needs_confirmation
                ? setConfirming(entry)
                : planOne.mutate({ sceneId: entry.id, confirmReplaceManual: false })
            }
            saving={save.isPending}
            saveError={save.error}
            onStartEdit={() => save.reset()}
            onSave={(units, done) =>
              save.mutate({ sceneId: entry.id, units }, { onSuccess: done })
            }
            sceneAudio={audioByScene[entry.id]}
            speechBusy={speechBusy}
            onMake={(unitId) => makeOne.mutate({ sceneId: entry.id, unitId })}
          />
        ))}
      </Stack>
      <ReplaceManualModal
        opened={confirming !== null}
        title="Plan the speech units again?"
        what={`The newest speech units of ${confirming?.title ?? "this scene"}`}
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
