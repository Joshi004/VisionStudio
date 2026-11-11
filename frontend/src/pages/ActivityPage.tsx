import { useEffect, useState } from "react";
import {
  Alert,
  Anchor,
  Button,
  Checkbox,
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
import { PurgeJobsModal } from "../components/jobs/PurgeJobsModal";
import { SchedulerHealthPanel } from "../components/jobs/SchedulerHealthPanel";
import {
  JOB_STATUSES,
  elapsedText,
  isJobStatus,
  isJobType,
  jobTypeLabel,
  jobTypeOptions,
  labPathFor,
  priorityText,
  showsPhase,
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

const EMPTY_SELECTION: ReadonlySet<number> = new Set();

export function ActivityPage() {
  const [openJobId, setOpenJobId] = useState<number | null>(null);
  // The jobs ticked for a purge on the GPU server, and the jobs the open purge dialog is about
  // (kept apart: the list refreshes after a purge, and the dialog must keep its answer).
  const [selection, setSelection] = useState<{ scope: string; ids: Set<number> }>({
    scope: "",
    ids: new Set(),
  });
  const [purgeIds, setPurgeIds] = useState<number[]>([]);
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
  // A new page or filter starts with nothing ticked: a selection made under another page or
  // filter is not used.
  const selectionScope = JSON.stringify([filter, page]);
  const selected = selection.scope === selectionScope ? selection.ids : EMPTY_SELECTION;
  // Only jobs on this page that can still be purged count, so a job that was just purged (or
  // one that left the page) is never sent again.
  const purgeable = (jobs ?? []).filter((job) => job.can_purge);
  const selectedIds = purgeable.filter((job) => selected.has(job.id)).map((job) => job.id);
  const allSelected = purgeable.length > 0 && selectedIds.length === purgeable.length;
  function select(ids: Set<number>) {
    setSelection({ scope: selectionScope, ids });
  }
  function toggleJob(jobId: number, checked: boolean) {
    const next = new Set(selected);
    if (checked) {
      next.add(jobId);
    } else {
      next.delete(jobId);
    }
    select(next);
  }
  function toggleAll(checked: boolean) {
    select(checked ? new Set(purgeable.map((job) => job.id)) : new Set());
  }
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

      {selectedIds.length > 0 && (
        <Group>
          <Button
            color="red"
            variant="light"
            size="compact-sm"
            onClick={() => setPurgeIds(selectedIds)}
          >
            Purge on GPU server ({selectedIds.length})
          </Button>
          <Button variant="subtle" size="compact-sm" onClick={() => select(new Set())}>
            Clear selection
          </Button>
        </Group>
      )}

      {jobs && jobs.length > 0 && (
        <Table.ScrollContainer minWidth={900}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={40}>
                  <Checkbox
                    aria-label="Select every job on this page that can be purged on the GPU server"
                    checked={allSelected}
                    indeterminate={selectedIds.length > 0 && !allSelected}
                    disabled={purgeable.length === 0}
                    onChange={(event) => toggleAll(event.currentTarget.checked)}
                  />
                </Table.Th>
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
                  <Table.Td onClick={(event) => event.stopPropagation()}>
                    <Checkbox
                      aria-label={`Select job ${job.id} for a purge on the GPU server`}
                      checked={selected.has(job.id) && job.can_purge}
                      disabled={!job.can_purge}
                      onChange={(event) => toggleJob(job.id, event.currentTarget.checked)}
                    />
                  </Table.Td>
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
                    {showsPhase(job.status) && priorityText(job) !== "" && (
                      <Text size="xs" c="dimmed">
                        {priorityText(job)}
                      </Text>
                    )}
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
      <PurgeJobsModal
        jobIds={purgeIds}
        onClose={() => {
          setPurgeIds([]);
          select(new Set());
        }}
      />
    </Stack>
  );
}
