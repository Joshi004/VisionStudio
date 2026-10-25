import { useState } from "react";
import { Link } from "react-router";
import {
  Alert,
  Badge,
  Button,
  Group,
  List,
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
import type { LabMusicRun } from "../../api/musicLab";
import {
  useLockMusicTake,
  useMusicTakes,
  useRejectMusicTake,
  useRunMusicTakes,
  useSelectMusicTake,
  type MusicTake,
  type MusicTakeItem,
} from "../../api/musicTakes";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { Measurements } from "../musicLab/MusicRunRating";

// The longest note the server accepts (`NOTE_MAX_CHARS`).
const NOTE_MAX_CHARS = 1000;

type MusicTakesPanelProps = {
  projectId: number;
};

/**
 * The recordings (takes) of every cue and hit of the music plan: one take for each wording, a
 * check of each, and the first that passes selected. You can select another take, reject one
 * with a note (the model then rewrites its prompt) or lock the selected one. Generating starts
 * only from the buttons here or from a pipeline run. When music is switched off the panel only
 * says so.
 */
export function MusicTakesPanel({ projectId }: MusicTakesPanelProps) {
  const { data, isLoading, isError, error } = useMusicTakes(projectId);
  const run = useRunMusicTakes(projectId);
  // What the confirmation is for: every item (no id) or one item id. None when closed.
  const [confirming, setConfirming] = useState<{ itemId?: string } | null>(
    null,
  );

  const musicOff = data !== undefined && !data.music_enabled;
  const blocked = data?.blocked_reason ?? null;
  const items = data?.items ?? [];
  const anyActive = items.some((item) => item.active);
  const anyWork = items.some((item) => item.action !== null && !item.active);

  const start = (itemId: string | undefined, confirmReplaceOwner: boolean) => {
    run.mutate({ itemId, confirmReplaceOwner });
  };
  const ask = (itemId: string | undefined) => {
    const targets = items.filter(
      (item) => itemId === undefined || item.id === itemId,
    );
    if (targets.some((item) => item.needs_confirmation)) {
      setConfirming({ itemId });
    } else {
      start(itemId, false);
    }
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Music takes</Title>
              <Text size="sm" c="dimmed">
                Each cue and hit is recorded once for every prompt wording.
                Every take is checked, and the first that passes is selected. A
                take that fails its check is made again with a new seed, up to
                the limit in the settings.
              </Text>
            </Stack>
            <Button
              onClick={() => ask(undefined)}
              loading={run.isPending || anyActive}
              disabled={
                isLoading || isError || musicOff || blocked !== null || !anyWork
              }
            >
              Make the music
            </Button>
          </Group>

          {musicOff && (
            <Alert color="gray" title="Music is switched off">
              This project is made without music, so this step is skipped. Turn
              music on in the{" "}
              <Link to={`/projects/${projectId}/settings`}>
                project settings
              </Link>{" "}
              to make it.
            </Alert>
          )}
          {!musicOff && blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {data && !musicOff && blocked === null && (
            <Text size="xs" c="dimmed">
              {data.wordings} {data.wordings === 1 ? "wording" : "wordings"} for
              each cue, and up to {data.max_retries}{" "}
              {data.max_retries === 1 ? "retry" : "retries"} of a take that
              fails its check. Both can be changed in the settings.
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the music takes">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the takes">
              {describeError(run.error)}
            </Alert>
          )}
        </Stack>
      </Paper>

      {items.map((item) => (
        <ItemCard
          key={item.id}
          projectId={projectId}
          item={item}
          onMake={() => ask(item.id)}
          making={run.isPending}
        />
      ))}

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Make the music again?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            You chose a take of a cue that has changed since. Making it again
            records new takes, and a new take that passes its checks replaces
            your choice. The earlier takes stay in the Music lab.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              onClick={() => {
                const itemId = confirming?.itemId;
                setConfirming(null);
                start(itemId, true);
              }}
            >
              Make again
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

function statusBadge(item: MusicTakeItem) {
  if (item.active) {
    return <Badge color="blue">Working</Badge>;
  }
  if (item.locked) {
    return <Badge color="teal">Locked</Badge>;
  }
  if (item.done) {
    return <Badge color="green">Done</Badge>;
  }
  if (item.out_of_date) {
    return <Badge color="yellow">Out of date</Badge>;
  }
  if (item.takes.length === 0) {
    return <Badge color="gray">Not made</Badge>;
  }
  return <Badge color="orange">Needs a choice</Badge>;
}

function makeLabel(item: MusicTakeItem) {
  if (item.action === "retry") {
    return "Make again";
  }
  if (item.action === "regenerate") {
    return "Make for the new detail";
  }
  return "Make";
}

type ItemCardProps = {
  projectId: number;
  item: MusicTakeItem;
  onMake: () => void;
  making: boolean;
};

function ItemCard({ projectId, item, onMake, making }: ItemCardProps) {
  const select = useSelectMusicTake(projectId);
  const lock = useLockMusicTake(projectId);
  // The take the owner is writing a note for. None when closed.
  const [rejecting, setRejecting] = useState<MusicTake | null>(null);
  const job = item.rewrite_job;
  const busy = item.active || select.isPending || lock.isPending;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <Title order={5}>{item.summary}</Title>
              {item.role === "hit" && <Badge size="sm">Hit</Badge>}
              {statusBadge(item)}
            </Group>
            <Text size="xs" c="dimmed">
              {item.kind}, {item.model}
              {item.requested_s !== null
                ? `, ${item.requested_s} s asked for`
                : ""}
              {item.retries_used > 0
                ? `. Retries used: ${item.retries_used}`
                : ""}
            </Text>
          </Stack>
          <Button
            variant="default"
            size="xs"
            onClick={onMake}
            loading={making}
            disabled={item.active || item.action === null}
          >
            {makeLabel(item)}
          </Button>
        </Group>

        {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
        {job?.status === "failed" && (
          <Alert color="red" title="The prompt could not be rewritten">
            {job.error ?? "The job failed."}
          </Alert>
        )}
        {item.out_of_date && (
          <Alert color="yellow" title="Out of date">
            <List size="sm">
              {item.reasons.map((reason) => (
                <List.Item key={reason}>{reason}</List.Item>
              ))}
            </List>
          </Alert>
        )}
        {!item.out_of_date && item.last_error !== null && (
          <Alert color="orange" title="No take is selected">
            {item.last_error}
          </Alert>
        )}
        {item.blocked_reason !== null && !item.done && (
          <Text size="sm" c="dimmed">
            {item.blocked_reason}
          </Text>
        )}

        {item.takes.length > 0 && (
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            {item.takes.map((take) => (
              <TakeCard
                key={take.id}
                take={take}
                itemLocked={item.locked}
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
function Recording({ run }: { run: LabMusicRun | null }) {
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

function takeBadge(take: MusicTake) {
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
  take: MusicTake;
  itemLocked: boolean;
  busy: boolean;
  onSelect: () => void;
  onReject: () => void;
  onLock: (locked: boolean) => void;
};

function TakeCard({
  take,
  itemLocked,
  busy,
  onSelect,
  onReject,
  onLock,
}: TakeCardProps) {
  const { run } = take;
  const hasSound = run?.url != null;
  const canSelect =
    hasSound && take.current && !take.rejected && !take.selected && !itemLocked;
  const canReject = hasSound && take.current && !take.inherited && !itemLocked;
  const canLock = take.selected && !take.locked && !take.inherited && hasSound;

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
            {take.wording !== null
              ? `Wording ${take.wording}`
              : "Rewritten prompt"}
            , round {take.round}
          </Text>
          {takeBadge(take)}
        </Group>
        {take.inherited && (
          <Text size="xs" c="dimmed">
            Locked in an earlier version of the plan and carried over.
          </Text>
        )}
        {!take.current && !take.inherited && (
          <Text size="xs" c="yellow.8">
            Made for an earlier version of the cue.
          </Text>
        )}
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
  take: MusicTake | null;
  onClose: () => void;
}) {
  const reject = useRejectMusicTake(projectId);
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
