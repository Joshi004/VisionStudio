import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import {
  useCharacterVoices,
  useMakeAllVoices,
  useMakeOneVoice,
  useNarratorVoice,
  type VoiceEntry,
} from "../../api/storyVoices";

type CharacterVoicesPanelProps = {
  projectId: number;
};

const STATUS: Record<VoiceEntry["status"], { label: string; color: string }> = {
  unavailable: { label: "Not available", color: "gray" },
  none: { label: "No voice", color: "gray" },
  in_progress: { label: "Making", color: "blue" },
  failed: { label: "Failed", color: "red" },
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

function labPath(characterId: number): string {
  return `/lab/characters?character=${characterId}`;
}

/** Where a voice that is being made stands, in words. */
function progressText(entry: VoiceEntry): string | null {
  if (entry.status !== "in_progress") {
    return null;
  }
  switch (entry.stage) {
    case "writing_description":
      return "Writing the voice description.";
    case "making_sample":
      return "Making the voice sample.";
    default:
      return null;
  }
}

function buttonLabel(entry: VoiceEntry): string {
  if (entry.status === "failed") {
    return "Retry";
  }
  if (entry.status === "ready" || entry.status === "out_of_date") {
    return "Make again";
  }
  return "Make voice";
}

type EntryRowProps = {
  entry: VoiceEntry;
  busy: boolean;
  onMake: () => void;
};

/**
 * One character: its status, the library character and the version the project pins, how far
 * its voice has got, why it failed, the description it was designed from, the sample and the
 * button that makes it.
 */
function EntryRow({ entry, busy, onMake }: EntryRowProps) {
  const status = STATUS[entry.status];
  const active = entry.status === "in_progress";
  const progress = progressText(entry);

  return (
    <Group align="flex-start" wrap="nowrap" gap="sm">
      <Badge variant="outline" color="gray" miw={120} style={{ flexShrink: 0, textTransform: "none" }}>
        {entry.id}
      </Badge>
      <Stack gap={4} style={{ flexGrow: 1 }}>
        <Group gap="xs">
          <Text size="sm" fw={500}>
            {entry.name}
          </Text>
          <Badge variant="light" color={status.color}>
            {status.label}
          </Badge>
          {entry.character_id !== null && entry.character_name !== null && (
            <Anchor component={Link} to={labPath(entry.character_id)} size="sm">
              {entry.character_name}
            </Anchor>
          )}
          {entry.needs_confirmation && (
            <Badge
              variant="light"
              color="teal"
              title="Chosen from the Character Lab: making a voice asks first, because it replaces the character's voice"
            >
              from the library
            </Badge>
          )}
          {entry.pinned_version !== null && (
            <Badge variant="light" title="The version of the character this project uses">
              pins v{entry.pinned_version}
            </Badge>
          )}
        </Group>
        {progress !== null && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="xs" c="dimmed">
              {progress}
            </Text>
          </Group>
        )}
        {entry.blocked_reason !== null && !active && (
          <Text size="xs" c="dimmed">
            {entry.blocked_reason}
          </Text>
        )}
        {entry.reasons.map((text) => (
          <Text key={text} size="xs" c="yellow.8">
            {text}
          </Text>
        ))}
        {entry.status === "failed" && entry.error !== null && (
          <Alert color="red" p="xs" title="The voice could not be made">
            {entry.error}
          </Alert>
        )}
        {entry.instruction !== null && (
          <Text size="xs" c="dimmed">
            Designed from: {entry.instruction}
          </Text>
        )}
        {entry.voice !== null && (
          <audio src={entry.voice.url} controls preload="metadata" style={{ width: "100%" }} />
        )}
      </Stack>
      <Button
        size="compact-sm"
        variant="default"
        loading={active}
        disabled={!entry.can_run || busy}
        onClick={onMake}
        style={{ flexShrink: 0 }}
      >
        {buttonLabel(entry)}
      </Button>
    </Group>
  );
}

/**
 * The character half of the Voices stage: for each defined character, the model writes a
 * description of its voice from the definition, one sample is made from it and saved as a voice,
 * and the character gets that voice as a new version that this project pins. **Make voices for
 * all** also derives the narrator's voice (below); a character chosen from the library is done
 * on its own, after the user confirms it.
 */
export function CharacterVoicesPanel({ projectId }: CharacterVoicesPanelProps) {
  const { data, isLoading, isError, error } = useCharacterVoices(projectId);
  const makeAll = useMakeAllVoices(projectId);
  const makeOne = useMakeOneVoice(projectId);
  // The character waiting for the user to agree to replace its voice.
  const [confirming, setConfirming] = useState<VoiceEntry | null>(null);

  const busy = makeAll.isPending || makeOne.isPending;
  const entries = data?.entries ?? [];
  const narrator = useNarratorVoice(projectId).data;
  // What "Make voices for all" would start: characters the pipeline made that may run and do not
  // have an up-to-date voice yet, and the narrator when it has none (or a derived one that is
  // out of date), never one chosen by hand.
  const narratorCount =
    narrator !== undefined &&
    narrator.can_run &&
    !narrator.needs_confirmation &&
    (narrator.status === "none" ||
      narrator.status === "failed" ||
      narrator.status === "out_of_date")
      ? 1
      : 0;
  const allCount =
    narratorCount +
    entries.filter(
      (entry) =>
        entry.can_run &&
        !entry.needs_confirmation &&
        (entry.status === "none" || entry.status === "failed" || entry.status === "out_of_date"),
    ).length;
  const skipped = makeAll.data?.skipped ?? [];

  const make = (entry: VoiceEntry) => {
    if (entry.needs_confirmation) {
      setConfirming(entry);
    } else {
      makeOne.mutate({ discoveryId: entry.id, confirmOverwrite: false });
    }
  };

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Character voices</Title>
            <Text size="sm" c="dimmed">
              Gives each defined character a voice: the model describes it from the
              character&apos;s definition, one sample is made and saved as a voice, and the
              character is saved as a new version that this project pins.
            </Text>
          </Stack>
          <Button
            onClick={() => makeAll.mutate()}
            loading={makeAll.isPending}
            disabled={isLoading || isError || busy || allCount === 0}
          >
            Make voices for all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the character voices">
            {describeError(error)}
          </Alert>
        )}
        {makeAll.isError && (
          <Alert color="red" title="Could not start the voices">
            {describeError(makeAll.error)}
          </Alert>
        )}
        {makeOne.isError && (
          <Alert color="red" title="Could not start the voice">
            {describeError(makeOne.error)}
          </Alert>
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not started">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={item.discovery_id} size="sm">
                  {item.name}: {item.reason}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        {data && data.discovery_version === null && (
          <Text size="sm" c="dimmed">
            Find the characters first (above), link and define them, then make their voices here.
          </Text>
        )}
        {entries.length > 0 && <Divider />}

        {entries.map((entry) => (
          <EntryRow key={entry.id} entry={entry} busy={busy} onMake={() => make(entry)} />
        ))}
      </Stack>

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Replace this character's voice?"
        centered
      >
        {confirming && (
          <Stack gap="md">
            <Text size="sm">
              {confirming.character_name ?? confirming.name} was chosen from the Character Lab.
              Making a voice for it replaces its voice. The earlier voice stays in the saved
              voices and in the character&apos;s version history.
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setConfirming(null)}>
                Cancel
              </Button>
              <Button
                color="red"
                onClick={() => {
                  makeOne.mutate({ discoveryId: confirming.id, confirmOverwrite: true });
                  setConfirming(null);
                }}
              >
                Make voice
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}
