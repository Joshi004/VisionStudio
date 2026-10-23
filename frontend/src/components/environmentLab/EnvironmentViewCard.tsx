import { Alert, Badge, Button, Group, Stack, Text } from "@mantine/core";

import type { EnvironmentView } from "../../api/environmentViews";

type EnvironmentViewCardProps = {
  view: EnvironmentView;
  /** Makes the picture again. Left out where the view cannot be remade. */
  onRemake?: () => void;
  remaking?: boolean;
};

const STATUS: Record<EnvironmentView["status"], { label: string; color: string }> = {
  none: { label: "No picture yet", color: "gray" },
  in_progress: { label: "Being made", color: "blue" },
  failed: { label: "Failed", color: "red" },
  ready: { label: "Picture ready", color: "green" },
};

const STAGE_LABELS: Record<NonNullable<EnvironmentView["stage"]>, string> = {
  writing_prompt: "writing the prompt",
  drawing: "drawing",
  waiting: "waiting for the left and right views",
};

/** One view of an environment: what it shows, where its picture stands and the picture. */
export function EnvironmentViewCard({ view, onRemake, remaking }: EnvironmentViewCardProps) {
  const status = STATUS[view.status];
  const busy = view.status === "in_progress";
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Text size="sm" fw={500}>
          {view.name}
        </Text>
        <Badge variant="outline" color="gray" size="sm" style={{ textTransform: "none" }}>
          {view.slug}
        </Badge>
        <Badge variant="light" size="sm">
          {view.side}, {view.framing}
        </Badge>
        <Badge variant="light" color={status.color} size="sm">
          {status.label}
          {view.stage !== null ? `: ${STAGE_LABELS[view.stage]}` : ""}
        </Badge>
        {view.reused && (
          <Badge variant="light" color="grape" size="sm">
            reused
          </Badge>
        )}
        {onRemake !== undefined && (
          <Button
            size="compact-xs"
            variant="default"
            loading={remaking}
            disabled={busy}
            onClick={onRemake}
          >
            {view.status === "ready" ? "Remake" : "Make"}
          </Button>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        {view.description}
      </Text>
      {view.scenes.length > 0 && (
        <Text size="xs" c="dimmed">
          Used by: {view.scenes.join(", ")}
        </Text>
      )}
      {view.reasons.map((reason) => (
        <Text key={reason} size="xs" c="yellow.8">
          {reason}
        </Text>
      ))}
      {view.error !== null && (
        <Alert color="red" p="xs">
          {view.error}
        </Alert>
      )}
      {view.states.length > 0 && (
        <Text size="xs" c="dimmed">
          Also drawn in the states: {view.states.map((state) => state.name).join(", ")}
        </Text>
      )}
      {view.image !== null && (
        <img
          src={view.image.url}
          alt={`${view.name}, view picture`}
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
