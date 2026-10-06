import { Alert, Anchor, Badge, Button, Group, Loader, Stack, Table, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Link } from "react-router";

import { describeError } from "../api/errors";
import { useProjects } from "../api/projects";
import { CreateProjectModal } from "../components/projects/CreateProjectModal";
import { capitalise, formatDuration } from "../format";

export function ProjectsPage() {
  const { data, isLoading, isError, error } = useProjects();
  const [modalOpened, modal] = useDisclosure(false);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Projects</Title>
        <Button onClick={modal.open}>New project</Button>
      </Group>

      {isLoading && <Loader size="sm" />}

      {isError && (
        <Alert color="red" title="Could not load the projects">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}

      {data && data.length === 0 && <Text c="dimmed">No projects yet.</Text>}

      {data && data.length > 0 && (
        <Table verticalSpacing="sm" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Orientation</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th>Voiceover</Table.Th>
              <Table.Th>Script</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.map((project) => (
              <Table.Tr key={project.id}>
                <Table.Td>
                  <Anchor component={Link} to={`/projects/${project.id}`}>
                    {project.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light">{capitalise(project.orientation)}</Badge>
                </Table.Td>
                <Table.Td>{new Date(project.created_at).toLocaleString()}</Table.Td>
                <Table.Td>
                  {project.voiceover_duration_s === null
                    ? "—"
                    : formatDuration(project.voiceover_duration_s)}
                </Table.Td>
                <Table.Td>{project.has_script ? "Yes" : "No"}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <CreateProjectModal opened={modalOpened} onClose={modal.close} />
    </Stack>
  );
}
