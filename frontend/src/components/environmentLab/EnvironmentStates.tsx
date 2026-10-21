import { Alert, Badge, Group, Loader, Stack, Text } from "@mantine/core";

import { useEnvironmentStates } from "../../api/environmentLab";
import { describeError } from "../../api/errors";

/**
 * The named states of one environment, such as night, read-only. A story project's resolution
 * creates each one, and its picture is the environment's canonical picture edited into that
 * condition, so the layout stays the same.
 */
export function EnvironmentStates({ environmentId }: { environmentId: number }) {
  const states = useEnvironmentStates(environmentId);

  if (states.data?.length === 0) {
    return null;
  }
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        States
      </Text>
      {states.isLoading && <Loader size="xs" />}
      {states.isError && (
        <Alert color="red" p="xs" title="Could not load the states">
          {describeError(states.error)}
        </Alert>
      )}
      {states.data?.map((state) => (
        <Stack key={state.id} gap={4}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {state.name}
            </Text>
            <Badge variant="outline" color="gray" size="sm" style={{ textTransform: "none" }}>
              {state.slug}
            </Badge>
            <Badge variant="light" color={state.image !== null ? "green" : "gray"} size="sm">
              {state.image !== null ? "picture ready" : "no picture yet"}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {state.description}
          </Text>
          {state.image !== null && (
            <img
              src={state.image.url}
              alt={`${state.name}, state picture`}
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
      ))}
    </Stack>
  );
}
