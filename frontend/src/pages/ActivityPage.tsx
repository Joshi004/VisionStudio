import { useState } from "react";
import { Alert, Anchor, Button, Group, Loader, Select, Stack, Table, Text, Title } from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../api/errors";
import { useJobs } from "../api/jobs";
import { isJobActive } from "../api/polling";
import { useProjects } from "../api/projects";
import { JobActions } from "../components/jobs/JobActions";
import { JobDetailDrawer } from "../components/jobs/JobDetailDrawer";
import { JobStatusBadge } from "../components/jobs/JobStatusBadge";
import { elapsedText, jobTypeLabel } from "../components/jobs/jobFormat";
import { formatDateTime } from "../format";
import { useNow } from "../hooks/useNow";

function firstLine(text: string | null): string {
  if (!text) {
    return "";
  }
  return text.split("\n", 1)[0];
}

export function ActivityPage() {
  const [projectFilter, setProjectFilter] = useState<string | null>(null);
  const [openJobId, setOpenJobId] = useState<number | null>(null);

  const projects = useProjects();
  const projectId = projectFilter === null ? undefined : Number(projectFilter);
  const { data: jobs, isLoading, isError, error, dataUpdatedAt } = useJobs(projectId);
  // Elapsed times are worked out from the stored times and the clock, which ticks once a
  // second while any job in the list is waiting or running.
  const now = useNow(jobs?.some(isJobActive) ?? false, dataUpdatedAt);

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Title order={2}>Activity</Title>
        <Select
          aria-label="Filter by project"
          placeholder="All projects"
          clearable
          data={(projects.data ?? []).map((project) => ({
            value: String(project.id),
            label: project.name,
          }))}
          value={projectFilter}
          onChange={setProjectFilter}
          w={260}
        />
      </Group>

      {isLoading && <Loader size="sm" />}

      {isError && (
        <Alert color="red" title="Could not load the jobs">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}

      {jobs && jobs.length === 0 && <Text c="dimmed">No jobs yet.</Text>}

      {jobs && jobs.length > 0 && (
        <Table.ScrollContainer minWidth={900}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Job</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>Project</Table.Th>
                <Table.Th>Scene</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th>Time</Table.Th>
                <Table.Th>Error</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {jobs.map((job) => (
                <Table.Tr
                  key={job.id}
                  onClick={() => setOpenJobId(job.id)}
                  style={{ cursor: "pointer" }}
                >
                  <Table.Td>{job.id}</Table.Td>
                  <Table.Td>{jobTypeLabel(job.type)}</Table.Td>
                  <Table.Td>
                    {job.project_id === null ? (
                      // The Video lab's jobs belong to no project.
                      <Anchor
                        component={Link}
                        to="/video-lab"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {job.project_name}
                      </Anchor>
                    ) : (
                      <Anchor
                        component={Link}
                        to={`/projects/${job.project_id}`}
                        onClick={(event) => event.stopPropagation()}
                      >
                        {job.project_name}
                      </Anchor>
                    )}
                  </Table.Td>
                  <Table.Td>{job.scene_index === null ? "—" : job.scene_index + 1}</Table.Td>
                  <Table.Td>
                    <JobStatusBadge job={job} />
                  </Table.Td>
                  <Table.Td>{formatDateTime(job.created_at)}</Table.Td>
                  <Table.Td>{elapsedText(job, now)}</Table.Td>
                  <Table.Td maw={260}>
                    <Text size="sm" c="red" truncate="end">
                      {firstLine(job.error)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <JobActions job={job} />
                      <Button
                        size="compact-xs"
                        variant="default"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenJobId(job.id);
                        }}
                      >
                        Details
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <JobDetailDrawer jobId={openJobId} onClose={() => setOpenJobId(null)} />
    </Stack>
  );
}
