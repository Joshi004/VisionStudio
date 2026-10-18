import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { useLabVideoRuns, type LabVideoRun } from "../../api/videoLab";
import { useNow } from "../../hooks/useNow";
import { formatDateTime } from "../../format";
import { H3_MODEL, videoModelLabel } from "../../videoModels";
import { JobActions } from "../jobs/JobActions";
import { elapsedText, serverEstimateText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { Thumb } from "../imageLab/ReferenceTray";
import {
  isLipSyncRun,
  isReferenceRun,
  negativePromptOf,
  paramsLine,
  referenceSummary,
  runStats,
} from "./videoLabView";

/** The badge colour of each model, so a group's runs can be told apart at a glance. */
function modelColor(model: LabVideoRun["video_model"]): string {
  if (model === "ltx-2.5") {
    return "blue";
  }
  return model === H3_MODEL ? "violet" : "gray";
}

/** How many reference pictures a group's header shows (a clip can have up to 9). */
const REFERENCE_THUMBS = 4;

/**
 * The runs one click started, in the order the models are listed: LTX-2.3, LTX-2.5, then
 * MiniMax H3 (which is also the alphabetical order of their ids).
 */
type RunGroup = { key: string; runs: LabVideoRun[] };

/** Groups consecutive runs that share a `group_key`. Runs arrive newest first. */
function groupRuns(runs: LabVideoRun[]): RunGroup[] {
  const groups: RunGroup[] = [];
  for (const run of runs) {
    const key = run.group_key ?? `run-${run.id}`;
    const last = groups[groups.length - 1];
    if (last !== undefined && last.key === key) {
      last.runs.push(run);
    } else {
      groups.push({ key, runs: [run] });
    }
  }
  for (const group of groups) {
    group.runs.sort((a, b) => a.video_model.localeCompare(b.video_model));
  }
  return groups;
}

/** What a waiting or running MiniMax H3 clip shows: the server's own numbers, once it has them. */
function h3WaitText(run: LabVideoRun): string {
  const server = serverEstimateText(run.gpus, run.estimated_run_seconds);
  return server === null
    ? "MiniMax H3 is a long GPU job. The server's GPUs and estimate show here once it has answered. This page updates by itself."
    : `The server says: ${server}. This page updates by itself.`;
}

function RunCard({ run, now }: { run: LabVideoRun; now: number }) {
  const job = run.job;
  const negative = negativePromptOf(run);
  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Badge variant="filled" color={modelColor(run.video_model)}>
              {videoModelLabel(run.video_model)}
            </Badge>
            {isLipSyncRun(run) && (
              <Badge
                variant="light"
                color="grape"
                title="Made to match a recorded speech: the character's lips follow it, and the speech is the clip's sound."
              >
                lip-sync
              </Badge>
            )}
            {isReferenceRun(run) && (
              <Badge
                variant="light"
                color="violet"
                title="Made from reference pictures (and voices, when given): the model follows each voice and makes its own sound."
              >
                reference
              </Badge>
            )}
            {job !== null && <JobStatusBadge job={job} />}
          </Group>
          {job !== null && <JobActions job={job} />}
        </Group>
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
            {/* Keyed by the file, so another run always loads fresh. */}
            <video
              key={run.id}
              src={run.url}
              controls
              preload="metadata"
              playsInline
              style={{ width: "100%", maxHeight: 460, background: "#000" }}
            />
            <Text size="xs" c="dimmed">
              {runStats(run)}
            </Text>
          </>
        ) : (
          job !== null &&
          isJobActive(job) && (
            <Text size="sm" c="dimmed">
              {run.video_model === H3_MODEL
                ? h3WaitText(run)
                : "The clip takes 5 to 10 minutes. This page updates by itself."}
            </Text>
          )
        )}
        {negative !== null && (
          <Text size="xs" c="dimmed" lineClamp={2} title={negative}>
            Negative prompt: {negative}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

type VideoLabRunListProps = {
  /** Puts a group's prompt and settings back into the form. */
  onLoad: (runs: LabVideoRun[]) => void;
};

/**
 * Every run, newest first. The runs of one click sit side by side, so the models can be
 * compared on the same prompt, first frame, length and seed.
 */
export function VideoLabRunList({ onLoad }: VideoLabRunListProps) {
  const runs = useLabVideoRuns();
  const all = runs.data?.pages.flat() ?? [];
  const groups = groupRuns(all);
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
        const frame = first.first_frame;
        const lastFrame = first.last_frame;
        const pictures = first.references.filter((picture) => picture.url !== null);
        return (
          <Paper key={group.key} withBorder p="md" radius="md">
            <Stack gap="sm">
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Group gap="sm" align="flex-start" wrap="nowrap">
                  {frame !== null && frame.url !== null && (
                    <div style={{ width: 56, flexShrink: 0 }}>
                      <Thumb url={frame.url} width={null} height={null} />
                    </div>
                  )}
                  {lastFrame !== null && lastFrame.url !== null && (
                    <div style={{ width: 56, flexShrink: 0 }}>
                      <Thumb url={lastFrame.url} width={null} height={null} />
                    </div>
                  )}
                  {pictures.slice(0, REFERENCE_THUMBS).map((picture) => (
                    <div key={`${picture.source}-${picture.id}`} style={{ width: 56, flexShrink: 0 }}>
                      <Thumb url={picture.url ?? ""} width={null} height={null} />
                    </div>
                  ))}
                  <Stack gap={2}>
                    <Text size="sm" lineClamp={4} style={{ whiteSpace: "pre-wrap" }}>
                      {first.prompt}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {paramsLine(first)}
                      {isReferenceRun(first)
                        ? ` · ${referenceSummary(first)}`
                        : isLipSyncRun(first)
                          ? " · lip-sync to a speech"
                          : lastFrame !== null
                            ? " · first to last frame"
                            : frame !== null
                              ? " · from a first frame"
                              : " · text-to-video"}{" "}
                      ·{" "}
                      {formatDateTime(first.created_at)}
                    </Text>
                  </Stack>
                </Group>
                {isLipSyncRun(first) ? (
                  // This form has no speech to give: a lip-synced clip is remade in its own tab.
                  <Text size="xs" c="dimmed" ta="right">
                    Made in the Characters tab
                  </Text>
                ) : (
                  <Button
                    size="compact-xs"
                    variant="default"
                    onClick={() => {
                      onLoad(group.runs);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  >
                    Load into the form
                  </Button>
                )}
              </Group>
              <SimpleGrid cols={{ base: 1, md: Math.min(group.runs.length, 3) }} spacing="sm">
                {group.runs.map((run) => (
                  <RunCard key={run.id} run={run} now={now} />
                ))}
              </SimpleGrid>
            </Stack>
          </Paper>
        );
      })}

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
