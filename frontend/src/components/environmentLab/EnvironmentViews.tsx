import { Alert, Loader, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useLabEnvironmentViews, useRemakeLabView } from "../../api/environmentViews";
import { EnvironmentViewCard } from "./EnvironmentViewCard";

/**
 * The views of one environment: the place seen from other directions than its canonical picture.
 * A story project's view plan creates each one, and its picture is the canonical picture edited
 * to look another way. A view can be made again from the newest canonical picture.
 */
export function EnvironmentViews({ environmentId }: { environmentId: number }) {
  const views = useLabEnvironmentViews(environmentId);
  const remake = useRemakeLabView(environmentId);

  if (views.data?.length === 0) {
    return null;
  }
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Views
      </Text>
      {views.isLoading && <Loader size="xs" />}
      {views.isError && (
        <Alert color="red" p="xs" title="Could not load the views">
          {describeError(views.error)}
        </Alert>
      )}
      {remake.isError && (
        <Alert color="red" p="xs" title="Could not start the picture">
          {describeError(remake.error)}
        </Alert>
      )}
      {views.data?.map((view) => (
        <EnvironmentViewCard
          key={view.id}
          view={view}
          onRemake={() => remake.mutate(view.id)}
          remaking={remake.isPending && remake.variables === view.id}
        />
      ))}
    </Stack>
  );
}
