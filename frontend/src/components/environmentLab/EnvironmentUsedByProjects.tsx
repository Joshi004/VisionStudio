import { Alert, Anchor, Badge, Group, Loader, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import { useEnvironmentProjects } from "../../api/environmentLinks";
import { describeError } from "../../api/errors";

/**
 * The story projects that use one environment, each with the version it pins, read-only. A
 * project's link is changed from the project: a pin never moves because of an edit made here,
 * so a project can be several versions behind. That is shown, and nothing more.
 */
export function EnvironmentUsedByProjects({ environmentId }: { environmentId: number }) {
  const usage = useEnvironmentProjects(environmentId);

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Used by projects
      </Text>
      {usage.isLoading && <Loader size="xs" />}
      {usage.isError && (
        <Alert color="red" p="xs" title="Could not load the projects">
          {describeError(usage.error)}
        </Alert>
      )}
      {usage.data?.length === 0 && (
        <Text size="xs" c="dimmed">
          No project uses this environment yet. A story project links it from its list of
          environments.
        </Text>
      )}
      {usage.data?.map((project) => (
        <Group key={`${project.project_id}:${project.discovery_id}`} gap="xs">
          <Anchor component={Link} to={`/projects/${project.project_id}`} size="sm" fw={500}>
            {project.project_name}
          </Anchor>
          <Text size="xs" c="dimmed">
            as {project.discovery_id}
          </Text>
          <Badge variant="light" title="The version of this environment the project uses">
            pins v{project.pinned_version}
          </Badge>
          {project.newer_version_available && (
            <Badge
              variant="light"
              color="yellow"
              title="The project keeps the pinned version until its environment is defined again."
            >
              v{project.newest_version} is newer
            </Badge>
          )}
        </Group>
      ))}
    </Stack>
  );
}
