import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Paper, SegmentedControl, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useMusicCatalog,
  useMusicLabRuns,
  useUpdateMusicRun,
  type LabMusicRun,
  type MusicCatalog,
  type MusicVerdict,
} from "../../api/musicLab";
import { isJobActive } from "../../api/polling";
import { useNow } from "../../hooks/useNow";
import { elapsedText } from "../jobs/jobFormat";
import { JobActions } from "../jobs/JobActions";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { LicenseBadge } from "./MusicLicense";
import { groupRuns, paramsLine, sentLines, stateFromRun, type MusicLabFormState } from "./musicLabView";

const VERDICTS: { value: MusicVerdict; label: string }[] = [
  { value: "good", label: "Good" },
  { value: "usable", label: "Usable" },
  { value: "bad", label: "Bad" },
];

/** What you decided after listening, and a note to yourself. Saved as soon as you choose. */
function Verdict({ run }: { run: LabMusicRun }) {
  const update = useUpdateMusicRun();
  const [note, setNote] = useState(run.note ?? "");

  function saveNote() {
    const trimmed = note.trim();
    if (trimmed !== (run.note ?? "")) {
      update.mutate({ runId: run.id, body: { note: trimmed === "" ? null : trimmed } });
    }
  }

  return (
    <Stack gap={4}>
      <Group gap="xs" wrap="nowrap">
        <SegmentedControl
          size="xs"
          // Nothing is selected while there is no verdict: "none" matches no button.
          value={run.verdict ?? "none"}
          onChange={(value) => {
            // Pressing the chosen button again clears the verdict.
            const verdict = value === run.verdict ? null : (value as MusicVerdict);
            update.mutate({ runId: run.id, body: { verdict } });
          }}
          data={[{ value: "none", label: "?", disabled: true }, ...VERDICTS]}
        />
        <TextInput
          size="xs"
          placeholder="A note: what you heard"
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
          onBlur={saveNote}
          maxLength={1000}
          style={{ flex: 1 }}
        />
      </Group>
      {update.isError && (
        <Text size="xs" c="red">
          {describeError(update.error)}
        </Text>
      )}
    </Stack>
  );
}

type RunCardProps = {
  run: LabMusicRun;
  now: number;
  catalog: MusicCatalog | undefined;
  onLoad: (state: MusicLabFormState) => void;
};

function RunCard({ run, now, catalog, onLoad }: RunCardProps) {
  const info = catalog?.models.find((entry) => entry.id === run.model);
  const failed = run.job?.status === "failed";
  const lines = sentLines(run, catalog);

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs">
            <Text size="sm" fw={600}>
              {run.model_label}
            </Text>
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

        {catalog && (
          <Group>
            <Button size="compact-xs" variant="subtle" onClick={() => onLoad(stateFromRun(run, catalog))}>
              Load into the form
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}

/**
 * The runs, newest first, grouped by the click that made them so the models can be heard one
 * after the other on the same brief. Nothing here is ever deleted.
 */
export function MusicLabRunList({ onLoad }: { onLoad: (state: MusicLabFormState) => void }) {
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
                <RunCard key={run.id} run={run} now={now} catalog={catalog.data} onLoad={onLoad} />
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
