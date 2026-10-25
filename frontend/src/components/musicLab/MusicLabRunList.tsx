import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useMusicCatalog, useMusicLabRuns, type LabMusicRun, type MusicCatalog } from "../../api/musicLab";
import { isJobActive } from "../../api/polling";
import { useNow } from "../../hooks/useNow";
import { elapsedText } from "../jobs/jobFormat";
import { JobActions } from "../jobs/JobActions";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { LicenseBadge } from "./MusicLicense";
import { Measurements, OutsideWindowLine, Verdict } from "./MusicRunRating";
import { sourceLine } from "./musicEditView";
import { groupRuns, paramsLine, sentLines, stateFromRun, type MusicLabFormState } from "./musicLabView";

type RunCardProps = {
  run: LabMusicRun;
  now: number;
  catalog: MusicCatalog | undefined;
  onLoad: (state: MusicLabFormState) => void;
  onEdit: (run: LabMusicRun) => void;
};

function RunCard({ run, now, catalog, onLoad, onEdit }: RunCardProps) {
  const info = catalog?.models.find((entry) => entry.id === run.model);
  const failed = run.job?.status === "failed";
  const lines = sentLines(run, catalog);
  const operation = catalog?.operations.find((entry) => entry.id === run.operation);

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs">
            <Text size="sm" fw={600}>
              {run.model_label}
            </Text>
            <Badge variant="light" color="gray">
              Run {run.id}
            </Badge>
            {info && <LicenseBadge model={info} />}
          </Group>
          {run.job && (
            <Group gap="xs">
              <JobStatusBadge job={run.job} />
              <Text size="xs" c="dimmed">
                {elapsedText(run.job, now)}
              </Text>
            </Group>
          )}
        </Group>

        {run.job && <JobActions job={run.job} />}

        {run.url !== null ? (
          <audio controls preload="none" src={run.url} style={{ width: "100%" }} />
        ) : isJobActive(run.job) ? (
          <Text size="xs" c="dimmed">
            Waiting for the sound. This page updates by itself. The first run on a model can take
            a few minutes.
          </Text>
        ) : null}

        {failed && run.job?.error && (
          <Alert color="red" title="The run failed" p="xs">
            <Text size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {run.job.error}
            </Text>
          </Alert>
        )}

        <Measurements run={run} />
        <OutsideWindowLine run={run} />

        {run.source !== null && (
          <Stack gap={2}>
            <Text size="xs" fw={600}>
              {operation?.label ?? run.operation}
            </Text>
            <Text size="xs" c="dimmed">
              {sourceLine(run.source)}
            </Text>
            {run.source.type !== "run" && run.source.url !== null && (
              <audio controls preload="none" src={run.source.url} style={{ width: "100%" }} />
            )}
          </Stack>
        )}

        <Text size="xs" c="dimmed">
          {paramsLine(run)}
        </Text>

        <details>
          <summary style={{ cursor: "pointer", fontSize: "var(--mantine-font-size-xs)" }}>
            What was sent
          </summary>
          <Stack gap={2} mt={4}>
            {lines.map((line) => (
              <Text key={line} size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {line}
              </Text>
            ))}
          </Stack>
        </details>

        {run.url !== null && <Verdict run={run} />}

        <Group gap="xs">
          {catalog && run.operation === null && (
            <Button size="compact-xs" variant="subtle" onClick={() => onLoad(stateFromRun(run, catalog))}>
              Load into the form
            </Button>
          )}
          {run.url !== null && (
            <Button size="compact-xs" variant="subtle" onClick={() => onEdit(run)}>
              Edit this run
            </Button>
          )}
        </Group>
      </Stack>
    </Paper>
  );
}

/**
 * The runs, newest first, grouped by the click that made them so the models can be heard one
 * after the other on the same brief. Nothing here is ever deleted.
 */
export function MusicLabRunList({
  onLoad,
  onEdit,
}: {
  onLoad: (state: MusicLabFormState) => void;
  onEdit: (run: LabMusicRun) => void;
}) {
  const runs = useMusicLabRuns();
  const catalog = useMusicCatalog();
  const all = runs.data?.pages.flat() ?? [];
  const groups = groupRuns(all, catalog.data);
  const active = all.some((run) => isJobActive(run.job));
  const now = useNow(active, runs.dataUpdatedAt);

  return (
    <Stack gap="md">
      <Text size="sm" fw={600}>
        Runs
      </Text>
      {runs.isLoading && <Loader size="sm" />}
      {runs.isError && (
        <Alert color="red" title="Could not load the runs">
          {describeError(runs.error)} Press Refresh to try again.
        </Alert>
      )}
      {runs.data && groups.length === 0 && (
        <Text size="sm" c="dimmed">
          No runs yet. The runs you start appear here, and stay: they are never deleted.
        </Text>
      )}

      {groups.map((group) => {
        const first = group.runs[0];
        const description = typeof first.brief.description === "string" ? first.brief.description : "";
        return (
          <Stack key={group.key} gap="xs">
            <Group gap="xs">
              <Badge variant="outline">{first.kind}</Badge>
              <Text size="xs" c="dimmed">
                {new Date(first.created_at).toLocaleString()}
              </Text>
            </Group>
            {description !== "" && (
              <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {description}
              </Text>
            )}
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {group.runs.map((run) => (
                <RunCard key={run.id} run={run} now={now} catalog={catalog.data} onLoad={onLoad} onEdit={onEdit} />
              ))}
            </SimpleGrid>
          </Stack>
        );
      })}

      {runs.hasNextPage && (
        <Group>
          <Button variant="default" onClick={() => runs.fetchNextPage()} loading={runs.isFetchingNextPage}>
            Show older runs
          </Button>
        </Group>
      )}
    </Stack>
  );
}
