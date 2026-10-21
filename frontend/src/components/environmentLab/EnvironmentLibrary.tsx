import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  UnstyledButton,
} from "@mantine/core";

import { useLibraryEnvironments, type LibraryEnvironment } from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import { eraText } from "./environmentLabView";

type EnvironmentLibraryProps = {
  onOpen: (environmentId: number) => void;
  onNew: () => void;
};

const PICTURE_STYLE = {
  width: "100%",
  aspectRatio: "16 / 9",
  objectFit: "cover",
  background: "var(--mantine-color-gray-1)",
  borderRadius: 4,
  display: "block",
} as const;

function EnvironmentCard({
  environment,
  onOpen,
}: {
  environment: LibraryEnvironment;
  onOpen: () => void;
}) {
  return (
    <Paper withBorder radius="md" p="xs">
      <UnstyledButton onClick={onOpen} style={{ display: "block", width: "100%" }}>
        <Stack gap={6}>
          {environment.image !== null ? (
            <img
              src={environment.image.url}
              alt={`${environment.name}, reference picture`}
              loading="lazy"
              style={PICTURE_STYLE}
            />
          ) : (
            <div
              style={{
                ...PICTURE_STYLE,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Text size="xs" c="dimmed">
                No picture yet
              </Text>
            </div>
          )}
          <Text size="sm" fw={600} lineClamp={1} title={environment.name}>
            {environment.name}
          </Text>
          <Text size="xs" c="dimmed" lineClamp={1} title={eraText(environment)}>
            {eraText(environment)}
          </Text>
          <Group gap={4}>
            {environment.version !== null && (
              <Badge variant="light" color="blue" title="The newest version">
                v{environment.version}
              </Badge>
            )}
            {environment.archived && (
              <Badge variant="light" color="orange">
                archived
              </Badge>
            )}
            {environment.origin !== null && (
              <Badge
                variant="light"
                color="teal"
                title={`Made from the project ${environment.origin.project_name}`}
              >
                from project
              </Badge>
            )}
          </Group>
        </Stack>
      </UnstyledButton>
    </Paper>
  );
}

/**
 * The library: every environment as a card, newest first. Archived environments are hidden
 * unless asked for. An environment is never deleted.
 */
export function EnvironmentLibrary({ onOpen, onNew }: EnvironmentLibraryProps) {
  const [showArchived, setShowArchived] = useState(false);
  const library = useLibraryEnvironments(showArchived);
  const environments = library.data?.pages.flatMap((page) => page.environments) ?? [];

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" maw={680}>
          Your places: a description and a wide reference picture of the empty place. Open one to
          make its picture. Every change makes a new version, and each version keeps its own
          picture.
        </Text>
        <Group gap="md">
          <Switch
            label="Show archived"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.currentTarget.checked)}
          />
          <Button onClick={onNew}>New environment</Button>
        </Group>
      </Group>

      {library.isLoading && <Loader size="sm" />}
      {library.isError && (
        <Alert color="red" title="Could not load the environments">
          {describeError(library.error)}
        </Alert>
      )}
      {library.data && environments.length === 0 && (
        <Text size="sm" c="dimmed">
          {showArchived ? "No environments yet." : "No environments yet. Press New environment."}
        </Text>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 4 }} spacing="sm">
        {environments.map((environment) => (
          <EnvironmentCard
            key={environment.id}
            environment={environment}
            onOpen={() => onOpen(environment.id)}
          />
        ))}
      </SimpleGrid>

      {library.hasNextPage && (
        <Group>
          <Button
            variant="default"
            loading={library.isFetchingNextPage}
            onClick={() => void library.fetchNextPage()}
          >
            Older
          </Button>
        </Group>
      )}
    </Stack>
  );
}
