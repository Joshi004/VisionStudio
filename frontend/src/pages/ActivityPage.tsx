import { useEffect, useState } from "react";
import {
  Alert,
  Anchor,
  Button,
  Group,
  Loader,
  MultiSelect,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../api/errors";
import { useJobsPage } from "../api/jobs";
import { isJobActive } from "../api/polling";
import { useProjects } from "../api/projects";
import { JobActions } from "../components/jobs/JobActions";
import { JobDetailDrawer } from "../components/jobs/JobDetailDrawer";
import { JobStatusBadge } from "../components/jobs/JobStatusBadge";
import { PoolCapacityPanel } from "../components/jobs/PoolCapacityPanel";
import { SchedulerHealthPanel } from "../components/jobs/SchedulerHealthPanel";
import {
  JOB_STATUSES,
  elapsedText,
  isJobStatus,
  isJobType,
  jobTypeLabel,
  jobTypeOptions,
  labPathFor,
} from "../components/jobs/jobFormat";
import { useActivityFilters } from "../components/jobs/useActivityFilters";
import { formatDateTime } from "../format";
import { useNow } from "../hooks/useNow";

function firstLine(text: string | null): string {
  if (!text) {
    return "";
  }
  return text.split("\n", 1)[0];
}

const PAGE_SIZE = 50;

/** The project filter's choice for the jobs of the labs, above the projects. */
const LAB_OPTION = { value: "lab", label: "Labs (no project)" };

const TYPE_OPTIONS = jobTypeOptions();

export function ActivityPage() {
  const [openJobId, setOpenJobId] = useState<number | null>(null);
  const { filter, page, hasFilters, setProject, setStatuses, setTypes, setPage, clear } =
    useActivityFilters();

  const projects = useProjects();
  const { data, isLoading, isError, error, dataUpdatedAt } = useJobsPage(filter, page, PAGE_SIZE);
  const jobs = data?.jobs;
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
  // If the jobs of the page are gone (a smaller list after a change, or a page number typed in
  // the address that is too high), go to the last page.
  useEffect(() => {
    if (data && page > pageCount) {
      setPage(pageCount);
    }
  }, [data, page, pageCount, setPage]);
  // Elapsed times are worked out from the stored times and the clock, which ticks once a
  // second while any job in the list is waiting or running.
  const now = useNow(jobs?.some(isJobActive) ?? false, dataUpdatedAt);

  return (
    <Stack gap="md">
      <Title order={2}>Activity</Title>

      <Group align="flex-end" gap="sm">
        <Select
          aria-label="Filter by project"
          placeholder="All projects"
          clearable
          data={[
            LAB_OPTION,
            ...(projects.data ?? []).map((project) => ({
              value: String(project.id),
              label: project.name,
            })),
          ]}
          value={filter.project === null ? null : String(filter.project)}
          onChange={(value) => {
            if (value === null) {
              setProject(null);
            } else if (value === LAB_OPTION.value) {
              setProject("lab");
            } else {
              setProject(Number(value));
            }
          }}
          w={240}
        />
        <MultiSelect
          aria-label="Filter by status"
          placeholder={filter.statuses.length === 0 ? "All statuses" : undefined}
          clearable
          data={JOB_STATUSES}
          value={filter.statuses}
          onChange={(values) => setStatuses(values.filter(isJobStatus))}
          w={260}
        />
        <MultiSelect
          aria-label="Filter by job type"
          placeholder={filter.types.length === 0 ? "All job types" : undefined}
          searchable
          clearable
          nothingFoundMessage="No such job type"
          data={TYPE_OPTIONS}
          value={filter.types}
          onChange={(values) => setTypes(values.filter(isJobType))}
          w={320}
        />
        {hasFilters && (
          <Button variant="default" onClick={clear}>
            Clear filters
          </Button>
        )}
      </Group>

      <PoolCapacityPanel />
      <SchedulerHealthPanel />

      {isLoading && <Loader size="sm" />}

      {isError && (
        <Alert color="red" title="Could not load the jobs">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}

      {jobs && jobs.length === 0 && page === 1 && (
        <Text c="dimmed">{hasFilters ? "No jobs match these filters." : "No jobs yet."}</Text>
      )}

      {jobs && jobs.length > 0 && (
        <Table.ScrollContainer minWidth={900}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Job</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>Project</Table.Th>
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
                      // The Lab's jobs belong to no project.
                      <Anchor
                        component={Link}
                        to={labPathFor(job.type)}
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

      {pageCount > 1 && (
        <Group justify="center">
          <Pagination total={pageCount} value={page} onChange={setPage} />
        </Group>
      )}

      <JobDetailDrawer jobId={openJobId} onClose={() => setOpenJobId(null)} />
    </Stack>
  );
}
