import { useState } from "react";
import { Alert, Anchor, Badge, Button, Checkbox, Group, Modal, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";

/** One story project that uses the library item, as the lab's "Used by projects" list gives it. */
export type AdoptProject = {
  project_id: number;
  project_name: string;
  discovery_id: string;
  pinned_version: number;
  newer_version_available: boolean;
  /** The project has a rendered final video. */
  complete: boolean;
  /** Ticked by default: not complete, behind the newest version, and able to adopt. */
  preselected: boolean;
  /** Why the project cannot adopt the newest version now, or null. */
  blocked_reason: string | null;
};

type AdoptVersionDialogProps = {
  opened: boolean;
  onClose: () => void;
  /** "character" or "environment", for the wording. */
  what: "character" | "environment";
  name: string;
  /** The version the projects would move to. */
  newestVersion: number;
  projects: AdoptProject[];
  onAdopt: (projectIds: number[]) => Promise<unknown>;
};

/**
 * Lets the user choose which projects move to the newest version of a character or an
 * environment. Projects that are not complete (no rendered final video) are ticked, finished ones
 * are not, and the user can change any tick. Adopting only moves the pins: what depends on the
 * item goes out of date in each project, and each project's **Regenerate out-of-date** rebuilds
 * it. Nothing is started here.
 */
export function AdoptVersionDialog({
  opened,
  onClose,
  what,
  name,
  newestVersion,
  projects,
  onAdopt,
}: AdoptVersionDialogProps) {
  return (
    <Modal opened={opened} onClose={onClose} title={`Adopt v${newestVersion} of ${name}`} centered>
      {/* Mounted only while open, so the ticks start from the pre-selection every time. */}
      <AdoptBody
        what={what}
        newestVersion={newestVersion}
        projects={projects}
        onAdopt={onAdopt}
        onClose={onClose}
      />
    </Modal>
  );
}

function AdoptBody({
  what,
  newestVersion,
  projects,
  onAdopt,
  onClose,
}: Pick<AdoptVersionDialogProps, "what" | "newestVersion" | "projects" | "onAdopt" | "onClose">) {
  const behind = projects.filter((project) => project.newer_version_available);
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(behind.filter((project) => project.preselected).map((p) => p.project_id)),
  );
  const [adopted, setAdopted] = useState<AdoptProject[] | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function toggle(projectId: number, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(projectId);
      } else {
        next.delete(projectId);
      }
      return next;
    });
  }

  async function submit() {
    const ids = behind
      .filter((project) => selected.has(project.project_id) && project.blocked_reason === null)
      .map((project) => project.project_id);
    setPending(true);
    setError(null);
    try {
      await onAdopt(ids);
      setAdopted(behind.filter((project) => ids.includes(project.project_id)));
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }

  if (adopted !== null) {
    return (
      <Stack gap="sm">
        <Text size="sm">
          {adopted.length} project{adopted.length === 1 ? "" : "s"} now use v{newestVersion}.
          Nothing was made again. Open each project and press <b>Regenerate out-of-date</b> to
          rebuild what depends on this {what}.
        </Text>
        {adopted.map((project) => (
          <Anchor
            key={project.project_id}
            component={Link}
            to={`/projects/${project.project_id}`}
            size="sm"
          >
            {project.project_name}
          </Anchor>
        ))}
        <Group justify="flex-end">
          <Button onClick={onClose}>Close</Button>
        </Group>
      </Stack>
    );
  }

  const chosen = behind.filter(
    (project) => selected.has(project.project_id) && project.blocked_reason === null,
  );

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        The pin of each chosen project moves to v{newestVersion}. Projects with a final video are
        not ticked, so finished work is left as it is.
      </Text>
      {behind.length === 0 && (
        <Text size="sm">Every project already uses v{newestVersion}.</Text>
      )}
      {behind.map((project) => (
        <Stack key={project.project_id} gap={2}>
          <Checkbox
            checked={selected.has(project.project_id) && project.blocked_reason === null}
            disabled={project.blocked_reason !== null || pending}
            onChange={(event) => toggle(project.project_id, event.currentTarget.checked)}
            label={
              <Group gap="xs">
                <Text size="sm" fw={500}>
                  {project.project_name}
                </Text>
                <Text size="xs" c="dimmed">
                  as {project.discovery_id}
                </Text>
                <Badge variant="light">pins v{project.pinned_version}</Badge>
                {project.complete && (
                  <Badge variant="light" color="teal" title="This project has a rendered final video.">
                    has a final render
                  </Badge>
                )}
              </Group>
            }
          />
          {project.blocked_reason !== null && (
            <Text size="xs" c="red" pl={28}>
              {project.blocked_reason}
            </Text>
          )}
        </Stack>
      ))}
      {error !== null && (
        <Alert color="red" p="xs" title="The version was not adopted">
          {describeError(error)}
        </Alert>
      )}
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose} disabled={pending}>
          Cancel
        </Button>
        <Button onClick={() => void submit()} loading={pending} disabled={chosen.length === 0}>
          Adopt v{newestVersion}
        </Button>
      </Group>
    </Stack>
  );
}
