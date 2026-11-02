import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Pagination,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useState } from "react";
import { Link } from "react-router";

import { describeError } from "../api/errors";
import { useProjectsPage } from "../api/projects";
import { CreateProjectModal } from "../components/projects/CreateProjectModal";
import { DeleteProjectModal } from "../components/projects/DeleteProjectModal";
import { capitalise } from "../format";

const PAGE_SIZE = 20;

export function ProjectsPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, error } = useProjectsPage(page, PAGE_SIZE);
  const projects = data?.projects;
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
  // After the last project of the last page is deleted, that page is gone: go to the new last one.
  if (data && page > pageCount) {
    setPage(pageCount);
  }
  const [modalOpened, modal] = useDisclosure(false);
  const [toDelete, setToDelete] = useState<{ id: number; name: string } | null>(null);

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

      {projects && projects.length === 0 && page === 1 && <Text c="dimmed">No projects yet.</Text>}

      {projects && projects.length > 0 && (
        <Table verticalSpacing="sm" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Orientation</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th>Story</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {projects.map((project) => (
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
                <Table.Td>{project.has_script ? "Yes" : "No"}</Table.Td>
                <Table.Td>
                  <Button
                    variant="subtle"
                    color="red"
                    size="compact-sm"
                    onClick={() => setToDelete({ id: project.id, name: project.name })}
                  >
                    Delete
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {pageCount > 1 && (
        <Group justify="center">
          <Pagination total={pageCount} value={page} onChange={setPage} />
        </Group>
      )}

      <CreateProjectModal opened={modalOpened} onClose={modal.close} />
      <DeleteProjectModal project={toDelete} onClose={() => setToDelete(null)} />
    </Stack>
  );
}
