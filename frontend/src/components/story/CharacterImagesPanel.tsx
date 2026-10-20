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

import {
  useCharacterImages,
  useMakeAllImages,
  useMakeOneImages,
  useRedoImageAngle,
  type ImageEntry,
} from "../../api/characterImages";
import type { Angle } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { ReferenceStrip } from "../characterLab/LookPicker";

type CharacterImagesPanelProps = {
  projectId: number;
};

const ANGLE_COUNT = 5;

const STATUS: Record<ImageEntry["status"], { label: string; color: string }> = {
  unavailable: { label: "Not available", color: "gray" },
  none: { label: "No images", color: "gray" },
  in_progress: { label: "Making", color: "blue" },
  failed: { label: "Failed", color: "red" },
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

/** What a character drawn from another's picture is to it, as a badge prefix. */
const RELATION_LABEL: Record<NonNullable<ImageEntry["made_from"]>["kind"], string> = {
  younger_self: "Younger self of",
  older_self: "Older self of",
  twin: "Twin of",
};

function labPath(characterId: number): string {
  return `/lab/characters?character=${characterId}`;
}

/** Where a look that is being made stands, in words. */
function progressText(entry: ImageEntry): string | null {
  if (entry.status !== "in_progress") {
    return null;
  }
  switch (entry.stage) {
    case "waiting_for_base":
      return `Waiting for ${entry.made_from?.name ?? "another character"}'s images.`;
    case "writing_prompt":
      return "Writing the image prompt.";
    case "making_master":
      return "Drawing the master picture.";
    case "making_angles":
      return `Making the other angles: ${entry.angles_ready} of ${ANGLE_COUNT} ready.`;
    default:
      return null;
  }
}

function buttonLabel(entry: ImageEntry): string {
  if (entry.status === "failed") {
    return "Retry";
  }
  if (entry.status === "ready" || entry.status === "out_of_date") {
    return "Make again";
  }
  return "Make images";
}

type EntryRowProps = {
  entry: ImageEntry;
  busy: boolean;
  onMake: () => void;
  onRedo: (lookId: number, angle: Angle) => void;
  redoingAngle: Angle | null;
};

/**
 * One character: its status, the library character and the version the project pins, how far
 * its look has got, why it failed, the five pictures and the button that makes them.
 */
function EntryRow({ entry, busy, onMake, onRedo, redoingAngle }: EntryRowProps) {
  const status = STATUS[entry.status];
  const active = entry.status === "in_progress";
  const progress = progressText(entry);
  const look = entry.look;
  // The strip is shown once there is a master to make the other angles from.
  const showStrip = look !== null && (look.status === "making_angles" || look.status === "ready");

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={120}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
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
            {entry.made_from !== null && (
              <Badge
                variant="light"
                color="grape"
                title="Drawn by editing this character's front picture, so both have the same face"
                style={{ textTransform: "none" }}
              >
                {RELATION_LABEL[entry.made_from.kind]} {entry.made_from.name}
              </Badge>
            )}
            {entry.needs_confirmation && (
              <Badge
                variant="light"
                color="teal"
                title="Chosen from the Character Lab: making images asks first, because it changes the character's current look"
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
            <Alert color="red" p="xs" title="The images could not be made">
              {entry.error}
            </Alert>
          )}
          {entry.failed_angles.length > 0 && entry.status !== "failed" && (
            <Text size="xs" c="red">
              Some angles could not be made; use Redo on them.
            </Text>
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
      {showStrip && look !== null && (
        <ReferenceStrip
          look={look}
          onRedo={(angle) => onRedo(look.id, angle)}
          redoingAngle={redoingAngle}
        />
      )}
    </Stack>
  );
}

/**
 * The Canonical Character Images stage: for each defined character, the Character Lab's look
 * pipeline runs with one candidate taken as the master, then makes the four other angles. When
 * the five pictures exist the character gets a new version and this project pins it.
 * **Make images for all** covers the characters made for this project; one chosen from the
 * library is done on its own, after the user confirms it.
 */
export function CharacterImagesPanel({ projectId }: CharacterImagesPanelProps) {
  const { data, isLoading, isError, error } = useCharacterImages(projectId);
  const makeAll = useMakeAllImages(projectId);
  const makeOne = useMakeOneImages(projectId);
  const redo = useRedoImageAngle(projectId);
  // The character waiting for the user to agree to change its current look.
  const [confirming, setConfirming] = useState<ImageEntry | null>(null);

  const busy = makeAll.isPending || makeOne.isPending;
  const entries = data?.entries ?? [];
  // What "Make images for all" would start: characters the pipeline made that may run and do
  // not have up-to-date images yet.
  const allCount = entries.filter(
    (entry) =>
      entry.can_run &&
      !entry.needs_confirmation &&
      (entry.status === "none" || entry.status === "failed" || entry.status === "out_of_date"),
  ).length;
  const skipped = makeAll.data?.skipped ?? [];

  const make = (entry: ImageEntry) => {
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
            <Title order={4}>Character images</Title>
            <Text size="sm" c="dimmed">
              Draws each defined character on a white backdrop from its definition: a master
              picture, then the three-quarter, side, back and face views. The finished look is
              saved to its Character Lab character as a new version that this project pins.
            </Text>
          </Stack>
          <Button
            onClick={() => makeAll.mutate()}
            loading={makeAll.isPending}
            disabled={isLoading || isError || busy || allCount === 0}
          >
            Make images for all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the character images">
            {describeError(error)}
          </Alert>
        )}
        {makeAll.isError && (
          <Alert color="red" title="Could not start the images">
            {describeError(makeAll.error)}
          </Alert>
        )}
        {makeOne.isError && (
          <Alert color="red" title="Could not start the images">
            {describeError(makeOne.error)}
          </Alert>
        )}
        {redo.isError && (
          <Alert color="red" title="Could not make the angle again">
            {describeError(redo.error)}
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
            Find the characters first (above), link and define them, then make their images here.
          </Text>
        )}
        {entries.length > 0 && <Divider />}

        {entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            busy={busy}
            onMake={() => make(entry)}
            onRedo={(lookId, angle) => redo.mutate({ lookId, angle })}
            redoingAngle={redo.isPending ? (redo.variables?.angle ?? null) : null}
          />
        ))}
      </Stack>

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Change this character's look?"
        centered
      >
        {confirming && (
          <Stack gap="md">
            <Text size="sm">
              {confirming.character_name ?? confirming.name} was chosen from the Character Lab.
              Making images for it makes a new look and sets it as the character&apos;s current
              look. Its earlier looks stay in the lab.
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
                Make images
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}
