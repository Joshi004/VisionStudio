import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { useVoiceLabRuns, type VoiceLabRun } from "../../api/voiceLab";
import { useNow } from "../../hooks/useNow";
import { formatDateTime } from "../../format";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { SaveVoiceModal } from "./SaveVoiceModal";
import { paramsLine } from "./voiceLabView";

function RunCard({
  run,
  now,
  onLoad,
}: {
  run: VoiceLabRun;
  now: number;
  onLoad: (run: VoiceLabRun) => void;
}) {
  const job = run.job;
  const [saving, setSaving] = useState(false);
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Badge variant="filled" color="grape">
              {run.mode}
            </Badge>
            {job !== null && <JobStatusBadge job={job} />}
          </Group>
          <Group gap="xs" wrap="nowrap">
            {job !== null && <JobActions job={job} />}
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => {
                onLoad(run);
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
            >
              Load into the form
            </Button>
          </Group>
        </Group>
        <Text size="sm" style={{ whiteSpace: "pre-wrap" }} lineClamp={6}>
          {run.text}
        </Text>
        {run.instruction !== null && (
          <Text size="xs" c="dimmed" lineClamp={3} title={run.instruction}>
            Instruction: {run.instruction}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          {paramsLine(run)} · {formatDateTime(run.created_at)}
        </Text>
        {job !== null && (
          <Text size="xs" c="dimmed">
            {elapsedText(job, now)}
            {job.attempt > 1 ? ` · attempt ${job.attempt}: the same request was sent again` : ""}
          </Text>
        )}
        {job?.status === "failed" && job.error && (
          <Alert color="red" title="The run failed" p="xs">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {job.error}
            </Text>
          </Alert>
        )}
        {run.url !== null ? (
          <>
            {/* Keyed by the run, so another run always loads fresh. */}
            <audio key={run.id} src={run.url} controls preload="metadata" style={{ width: "100%" }} />
            <Group>
              <Button size="compact-sm" variant="default" onClick={() => setSaving(true)}>
                Save as a voice
              </Button>
            </Group>
            {saving && <SaveVoiceModal run={run} opened onClose={() => setSaving(false)} />}
          </>
        ) : (
          job !== null &&
          isJobActive(job) && (
            <Text size="sm" c="dimmed">
              The speech takes one to three minutes. This page updates by itself.
            </Text>
          )
        )}
      </Stack>
    </Paper>
  );
}

type VoiceLabRunListProps = {
  /** Puts a run's text and settings back into the form. */
  onLoad: (run: VoiceLabRun) => void;
};

/** Every run, newest first. They stay: nothing is deleted. */
export function VoiceLabRunList({ onLoad }: VoiceLabRunListProps) {
  const runs = useVoiceLabRuns();
  const all = runs.data?.pages.flat() ?? [];
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
          {describeError(runs.error)}
        </Alert>
      )}
      {runs.data && all.length === 0 && (
        <Text size="sm" c="dimmed">
          No runs yet. The runs you start appear here, and stay: they are never deleted.
        </Text>
      )}
      {all.map((run) => (
        <RunCard key={run.id} run={run} now={now} onLoad={onLoad} />
      ))}
      {runs.hasNextPage && (
        <Button
          variant="default"
          onClick={() => void runs.fetchNextPage()}
          loading={runs.isFetchingNextPage}
        >
          Older runs
        </Button>
      )}
    </Stack>
  );
}
