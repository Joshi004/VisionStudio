import { useState } from "react";
import { Alert, Anchor, Badge, Button, Group, Loader, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import { useAdoptCharacterVersion, useCharacterProjects } from "../../api/characterLinks";
import { describeError } from "../../api/errors";
import { AdoptVersionDialog } from "./AdoptVersionDialog";

/**
 * The story projects that use one character, each with the version it pins. A pin never moves
 * because of an edit made here, so a project can be several versions behind. **Adopt** lets the
 * user choose which projects move to the newest version (PHASE-042): projects without a final
 * video are ticked by default, and only the pins move.
 */
export function UsedByProjects({ characterId, name }: { characterId: number; name: string }) {
  const usage = useCharacterProjects(characterId);
  const adopt = useAdoptCharacterVersion(characterId);
  const [dialogOpen, setDialogOpen] = useState(false);

  const projects = usage.data ?? [];
  const newest = projects.find((project) => project.newest_version !== null)?.newest_version;
  const anyBehind = projects.some((project) => project.newer_version_available);

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text size="sm" fw={600}>
          Used by projects
        </Text>
        {anyBehind && newest != null && (
          <Button size="compact-xs" variant="light" onClick={() => setDialogOpen(true)}>
            Adopt v{newest}...
          </Button>
        )}
      </Group>
      {newest != null && (
        <AdoptVersionDialog
          opened={dialogOpen}
          onClose={() => setDialogOpen(false)}
          what="character"
          name={name}
          newestVersion={newest}
          projects={projects}
          onAdopt={(projectIds) => adopt.mutateAsync({ version: newest, projectIds })}
        />
      )}
      {usage.isLoading && <Loader size="xs" />}
      {usage.isError && (
        <Alert color="red" p="xs" title="Could not load the projects">
          {describeError(usage.error)}
        </Alert>
      )}
      {usage.data?.length === 0 && (
        <Text size="xs" c="dimmed">
          No project uses this character yet. A story project links it from its list of characters.
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
          <Badge variant="light" title="The version of this character the project uses">
            pins v{project.pinned_version}
          </Badge>
          {project.newer_version_available && (
            <Badge
              variant="light"
              color="yellow"
              title="The project keeps the pinned version until it adopts the newer one."
            >
              v{project.newest_version} is newer
            </Badge>
          )}
        </Group>
      ))}
    </Stack>
  );
}
