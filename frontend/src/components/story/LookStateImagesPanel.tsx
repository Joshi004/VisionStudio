import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import type { Angle } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import {
  useLookStateImages,
  useMakeAllLookStateImages,
  useMakeLookImages,
  useMakeStateImage,
  useRedoLookAngle,
  type LookStateImageItem,
} from "../../api/lookStateImages";
import { ReferenceStrip } from "../characterLab/LookPicker";

type LookStateImagesPanelProps = {
  projectId: number;
};

const ANGLE_COUNT = 5;

const STATUS: Record<LookStateImageItem["status"], { label: string; color: string }> = {
  unavailable: { label: "Not available", color: "gray" },
  none: { label: "No pictures", color: "gray" },
  in_progress: { label: "Making", color: "blue" },
  failed: { label: "Failed", color: "red" },
  ready: { label: "Ready", color: "green" },
};

/** Where an item that is being made stands, in words. */
function progressText(item: LookStateImageItem): string | null {
  if (item.status !== "in_progress") {
    return null;
  }
  switch (item.stage) {
    case "drawing":
      return "Drawing the picture. This takes a few minutes.";
    case "making_master":
      return "Drawing the new look.";
    case "making_angles":
      return `Making the other angles: ${item.angles_ready} of ${ANGLE_COUNT} ready.`;
    default:
      return null;
  }
}

function buttonLabel(item: LookStateImageItem): string {
  return item.status === "failed" ? "Retry" : "Make pictures";
}

type ItemRowProps = {
  item: LookStateImageItem;
  busy: boolean;
  onMake: () => void;
  onRedo: (lookId: number, angle: Angle) => void;
  redoingAngle: Angle | null;
};

/**
 * One new look or environment state: what it is, which scenes use it, how far its pictures
 * have got, why it failed, the pictures themselves and the button that makes them.
 */
function ItemRow({ item, busy, onMake, onRedo, redoingAngle }: ItemRowProps) {
  const status = STATUS[item.status];
  const active = item.status === "in_progress";
  const progress = progressText(item);
  const look = item.look;
  // A look's strip is shown once there is a master to make the other angles from.
  const showStrip = look !== null && (look.status === "making_angles" || look.status === "ready");

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color={item.kind === "look" ? "grape" : "teal"}
          miw={70}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {item.kind === "look" ? "Look" : "State"}
        </Badge>
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {item.name}
            </Text>
            <Text size="sm" c="dimmed">
              of {item.subject_name}
            </Text>
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {item.description}
          </Text>
          {item.scenes.length > 0 && (
            <Text size="xs" c="dimmed">
              Used in: {item.scenes.join(", ")}
            </Text>
          )}
          {progress !== null && (
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="xs" c="dimmed">
                {progress}
              </Text>
            </Group>
          )}
          {item.blocked_reason !== null && !active && item.status !== "ready" && (
            <Text size="xs" c="dimmed">
              {item.blocked_reason}
            </Text>
          )}
          {item.status === "failed" && item.error !== null && (
            <Alert color="red" p="xs" title="The pictures could not be made">
              {item.error}
            </Alert>
          )}
          {item.failed_angles.length > 0 && item.status !== "failed" && (
            <Text size="xs" c="red">
              Some angles could not be made; use Redo on them.
            </Text>
          )}
        </Stack>
        {item.status !== "ready" && (
          <Button
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!item.can_run || busy}
            onClick={onMake}
            style={{ flexShrink: 0 }}
          >
            {buttonLabel(item)}
          </Button>
        )}
      </Group>
      {showStrip && look !== null && (
        <ReferenceStrip
          look={look}
          onRedo={(angle) => onRedo(look.id, angle)}
          redoingAngle={redoingAngle}
        />
      )}
      {item.image !== null && (
        <img
          src={item.image.url}
          alt={`${item.subject_name}, ${item.name}`}
          loading="lazy"
          style={{
            width: "100%",
            maxWidth: 420,
            aspectRatio: "16 / 9",
            objectFit: "cover",
            borderRadius: 4,
            display: "block",
            background: "var(--mantine-color-gray-1)",
          }}
        />
      )}
    </Stack>
  );
}

/**
 * The pictures of the new looks and environment states the resolution created. A new look is
 * the character's canonical front picture edited into the new outfit, then turned to the other
 * angles; a new state is the environment's canonical picture edited into the new condition.
 * Each is made once and shared by every scene that uses it. The finished pictures are saved as
 * a new version of the character or environment that this project pins.
 */
export function LookStateImagesPanel({ projectId }: LookStateImagesPanelProps) {
  const { data, isLoading, isError, error } = useLookStateImages(projectId);
  const makeAll = useMakeAllLookStateImages(projectId);
  const makeLook = useMakeLookImages(projectId);
  const makeState = useMakeStateImage(projectId);
  const redo = useRedoLookAngle(projectId);

  const busy = makeAll.isPending || makeLook.isPending || makeState.isPending;
  const items = data?.items ?? [];
  const allCount = items.filter((item) => item.can_run).length;
  const skipped = makeAll.data?.skipped ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>New looks and states: pictures</Title>
            <Text size="sm" c="dimmed">
              Draws each new outfit and each new condition (such as night) by editing the
              canonical picture, so the face and the room stay the same. Only the new ones are
              made, once each.
            </Text>
          </Stack>
          <Button
            onClick={() => makeAll.mutate()}
            loading={makeAll.isPending}
            disabled={isLoading || isError || busy || allCount === 0}
          >
            Make pictures for all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the pictures of the new looks and states">
            {describeError(error)}
          </Alert>
        )}
        {makeAll.isError && (
          <Alert color="red" title="Could not start the pictures">
            {describeError(makeAll.error)}
          </Alert>
        )}
        {makeLook.isError && (
          <Alert color="red" title="Could not start the pictures">
            {describeError(makeLook.error)}
          </Alert>
        )}
        {makeState.isError && (
          <Alert color="red" title="Could not start the picture">
            {describeError(makeState.error)}
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
                <Text key={`${item.kind}-${item.id}`} size="sm">
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
        {data && data.blocked_reason === null && items.length === 0 && (
          <Text size="sm" c="dimmed">
            The newest resolution created no new looks or states, so there is nothing to draw.
          </Text>
        )}
        {items.length > 0 && <Divider />}

        {items.map((item) => (
          <ItemRow
            key={`${item.kind}-${item.id}`}
            item={item}
            busy={busy}
            onMake={() =>
              item.kind === "look" ? makeLook.mutate(item.id) : makeState.mutate(item.id)
            }
            onRedo={(lookId, angle) => redo.mutate({ lookId, angle })}
            redoingAngle={redo.isPending ? (redo.variables?.angle ?? null) : null}
          />
        ))}
      </Stack>
    </Paper>
  );
}
