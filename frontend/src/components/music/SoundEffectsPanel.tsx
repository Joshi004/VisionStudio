import { useState } from "react";
import { Link } from "react-router";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useLockSoundEffectTake,
  useRejectSoundEffectTake,
  useRunSoundEffects,
  useSelectSoundEffectTake,
  useSoundEffects,
  type SoundEffect,
  type SoundEffectTake,
} from "../../api/soundEffects";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { Measurements } from "../musicLab/MusicRunRating";

// The longest note the server accepts (`NOTE_MAX_CHARS`).
const NOTE_MAX_CHARS = 1000;

type SoundEffectsPanelProps = {
  projectId: number;
};

/**
 * The project's two sound effects (EXM-006): the sound played at every graphic and the sound
 * played at every piece of evidence. The model writes a prompt for each, several takes are
 * recorded, every take is checked, and the first that passes is selected. You can select another
 * take, reject one with a note (the model then rewrites the prompt), lock the selected one, or
 * make a sound again. Generating starts only from the buttons here or from a pipeline run. When
 * the switch is off the panel only says so.
 */
export function SoundEffectsPanel({ projectId }: SoundEffectsPanelProps) {
  const { data, isLoading, isError, error } = useSoundEffects(projectId);
  const run = useRunSoundEffects(projectId);

  const switchedOff = data !== undefined && !data.sound_effects;
  const nothingNeeded = data !== undefined && data.sound_effects && !data.wanted;
  const blocked = data?.blocked_reason ?? null;
  const sounds = data?.sounds ?? [];
  const anyActive = sounds.some((sound) => sound.active);
  const anyWork = sounds.some((sound) => sound.action !== null && !sound.active);

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Sound effects</Title>
              <Text size="sm" c="dimmed">
                One soft sound for every graphic and one for every piece of
                evidence, made once for the project. The model writes the
                prompt, several takes are recorded and checked, and the first
                that passes is selected.
              </Text>
            </Stack>
            <Button
              onClick={() => run.mutate({})}
              loading={run.isPending || anyActive}
              disabled={
                isLoading ||
                isError ||
                switchedOff ||
                nothingNeeded ||
                blocked !== null ||
                !anyWork
              }
            >
              Make the sound effects
            </Button>
          </Group>

          {switchedOff && (
            <Alert color="gray" title="Sound effects are switched off">
              This project is made without its own sound effects, so this step
              is skipped. Turn them on in the{" "}
              <Link to={`/projects/${projectId}/settings`}>
                project settings
              </Link>{" "}
              to make them.
            </Alert>
          )}
          {nothingNeeded && (
            <Text size="sm" c="dimmed">
              Nothing to make: the project has neither graphics nor evidence.
            </Text>
          )}
          {!switchedOff && !nothingNeeded && blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {data && data.wanted && blocked === null && (
            <Text size="xs" c="dimmed">
              {data.takes_per_prompt}{" "}
              {data.takes_per_prompt === 1 ? "take" : "takes"} of each sound,
              and up to {data.max_retries}{" "}
              {data.max_retries === 1 ? "retry" : "retries"} of a take that
              fails its check. Both can be changed in the settings.
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the sound effects">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the sound effects">
              {describeError(run.error)}
            </Alert>
          )}
        </Stack>
      </Paper>

      {data?.wanted &&
        sounds.map((sound) => (
          <SoundCard
            key={sound.role}
            projectId={projectId}
            sound={sound}
            onMake={() => run.mutate({ role: sound.role })}
            making={run.isPending}
          />
        ))}
    </Stack>
  );
}

function statusBadge(sound: SoundEffect) {
  if (sound.active) {
    return <Badge color="blue">Working</Badge>;
  }
  if (sound.locked) {
    return <Badge color="teal">Locked</Badge>;
  }
  if (sound.done) {
    return <Badge color="green">Done</Badge>;
  }
  if (sound.takes.length === 0) {
    return <Badge color="gray">Not made</Badge>;
  }
  return <Badge color="orange">Needs a choice</Badge>;
}

function makeLabel(sound: SoundEffect) {
  if (sound.action === "retry") {
    return "Retry";
  }
  if (sound.action === "generate") {
    return "Make";
  }
  return "Make again";
}

type SoundCardProps = {
  projectId: number;
  sound: SoundEffect;
  onMake: () => void;
  making: boolean;
};

function SoundCard({ projectId, sound, onMake, making }: SoundCardProps) {
  const select = useSelectSoundEffectTake(projectId);
  const lock = useLockSoundEffectTake(projectId);
  // The take the owner is writing a note for. None when closed.
  const [rejecting, setRejecting] = useState<SoundEffectTake | null>(null);
  const job = sound.prompt_job;
  const busy = sound.active || select.isPending || lock.isPending;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <Title order={5}>{sound.label}</Title>
              {statusBadge(sound)}
            </Group>
            <Text size="xs" c="dimmed">
              Round {sound.round}
              {sound.retries_used > 0
                ? `. Retries used: ${sound.retries_used}`
                : ""}
            </Text>
          </Stack>
          <Button
            variant="default"
            size="xs"
            onClick={onMake}
            loading={making}
            disabled={sound.active || sound.locked || sound.blocked_reason !== null}
          >
            {makeLabel(sound)}
          </Button>
        </Group>

        {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
        {job?.status === "failed" && (
          <Alert color="red" title="The prompt could not be written">
            {job.error ?? "The job failed."}
          </Alert>
        )}
        {sound.last_error !== null && !sound.done && (
          <Alert color="orange" title="No take is selected">
            {sound.last_error}
          </Alert>
        )}
        {sound.blocked_reason !== null && !sound.done && (
          <Text size="sm" c="dimmed">
            {sound.blocked_reason}
          </Text>
        )}

        {sound.takes.length > 0 && (
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            {sound.takes.map((take) => (
              <TakeCard
                key={take.id}
                take={take}
                soundLocked={sound.locked}
                busy={busy}
                onSelect={() => select.mutate(take.id)}
                onReject={() => setRejecting(take)}
                onLock={(locked) => lock.mutate({ takeId: take.id, locked })}
              />
            ))}
          </SimpleGrid>
        )}
        {select.isError && (
          <Alert color="red" title="Could not select the take">
            {describeError(select.error)}
          </Alert>
        )}
        {lock.isError && (
          <Alert color="red" title="Could not change the lock">
            {describeError(lock.error)}
          </Alert>
        )}

        <RejectModal
          projectId={projectId}
          take={rejecting}
          onClose={() => setRejecting(null)}
        />
      </Stack>
    </Paper>
  );
}

/** The player, or why there is none yet. */
function Recording({ run }: { run: SoundEffectTake["run"] }) {
  if (run === null) {
    return null;
  }
  if (run.url !== null) {
    return (
      <audio controls preload="none" src={run.url} style={{ width: "100%" }} />
    );
  }
  if (isJobActive(run.job)) {
    return (
      <Text size="xs" c="dimmed">
        Waiting for the sound. This page updates by itself.
      </Text>
    );
  }
  return null;
}

function takeBadge(take: SoundEffectTake) {
  if (take.rejected) {
    return (
      <Badge color="red" variant="light">
        Rejected
      </Badge>
    );
  }
  if (take.selected) {
    return (
      <Badge variant="light">
        {take.locked
          ? "Locked"
          : take.selected_by === "owner"
            ? "Chosen by you"
            : "Selected"}
      </Badge>
    );
  }
  switch (take.status) {
    case "generating":
      return (
        <Badge color="blue" variant="light">
          Recording
        </Badge>
      );
    case "checking":
      return (
        <Badge color="blue" variant="light">
          Checking
        </Badge>
      );
    case "failed":
      return (
        <Badge color="red" variant="light">
          Failed
        </Badge>
      );
    case "check_failed":
      return (
        <Badge color="orange" variant="light">
          Did not pass
        </Badge>
      );
    default:
      return (
        <Badge color="green" variant="light">
          Passed
        </Badge>
      );
  }
}

type TakeCardProps = {
  take: SoundEffectTake;
  soundLocked: boolean;
  busy: boolean;
  onSelect: () => void;
  onReject: () => void;
  onLock: (locked: boolean) => void;
};

function TakeCard({
  take,
  soundLocked,
  busy,
  onSelect,
  onReject,
  onLock,
}: TakeCardProps) {
  const { run } = take;
  const hasSound = run?.url != null;
  const canSelect = hasSound && !take.rejected && !take.selected && !soundLocked;
  const canReject = hasSound && !take.rejected && !soundLocked;
  const canLock = take.selected && !take.locked && hasSound;

  return (
    <Paper
      withBorder
      p="sm"
      radius="md"
      style={
        take.selected
          ? { borderColor: "var(--mantine-color-blue-6)" }
          : undefined
      }
    >
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={600}>
            Round {take.round}, {take.requested_s} s
          </Text>
          {takeBadge(take)}
        </Group>
        <Recording run={run} />
        {run !== null && <Measurements run={run} />}
        {take.check !== null && take.check.passed && (
          <Text size="xs" c="green">
            Passed the checks.
          </Text>
        )}
        {take.problems.length > 0 && (
          <Text size="xs" c="orange">
            {take.problems.join(" ")}
          </Text>
        )}
        {take.rejected && take.reject_note !== null && (
          <Text
            size="xs"
            c="dimmed"
            style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
          >
            Your note: {take.reject_note}
          </Text>
        )}
        <details>
          <summary
            style={{
              cursor: "pointer",
              fontSize: "var(--mantine-font-size-xs)",
            }}
          >
            What was sent (seed {take.seed})
          </summary>
          <Text
            size="xs"
            mt={4}
            ff="monospace"
            style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
          >
            {JSON.stringify(take.fields, null, 2)}
          </Text>
        </details>
        <Group gap="xs">
          {canSelect && (
            <Button
              variant="default"
              size="xs"
              disabled={busy}
              onClick={onSelect}
            >
              Select
            </Button>
          )}
          {canReject && (
            <Button
              variant="default"
              size="xs"
              color="red"
              disabled={busy}
              onClick={onReject}
            >
              Reject
            </Button>
          )}
          {canLock && (
            <Button
              variant="default"
              size="xs"
              disabled={busy}
              onClick={() => onLock(true)}
            >
              Lock
            </Button>
          )}
          {take.locked && (
            <Button
              variant="default"
              size="xs"
              disabled={busy}
              onClick={() => onLock(false)}
            >
              Unlock
            </Button>
          )}
        </Group>
      </Stack>
    </Paper>
  );
}

function RejectModal({
  projectId,
  take,
  onClose,
}: {
  projectId: number;
  take: SoundEffectTake | null;
  onClose: () => void;
}) {
  const reject = useRejectSoundEffectTake(projectId);
  const [note, setNote] = useState("");
  const trimmed = note.trim();

  const close = () => {
    setNote("");
    reject.reset();
    onClose();
  };

  return (
    <Modal
      opened={take !== null}
      onClose={close}
      title="Reject this take"
      centered
    >
      <Stack gap="md">
        <Text size="sm">
          Say what is wrong with the sound. The model reads your note, the
          prompt and what was measured, writes a new prompt, and a new take is
          made from it.
        </Text>
        <Textarea
          label="What is wrong"
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
          maxLength={NOTE_MAX_CHARS}
          autosize
          minRows={3}
          data-autofocus
        />
        {reject.isError && (
          <Alert color="red" title="Could not reject the take">
            {describeError(reject.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>
            Cancel
          </Button>
          <Button
            color="red"
            loading={reject.isPending}
            disabled={trimmed === "" || take === null}
            onClick={() => {
              if (take === null) {
                return;
              }
              reject.mutate(
                { takeId: take.id, note: trimmed },
                { onSuccess: close },
              );
            }}
          >
            Reject and rewrite
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
