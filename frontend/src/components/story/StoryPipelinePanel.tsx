import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Collapse,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";

import { describeError } from "../../api/errors";
import { useCancelJob } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import {
  storyPipelineKey,
  useContinueStoryPipeline,
  useStartStoryPipeline,
  useStoryPipeline,
  type PipelineScope,
  type PipelineStepProgress,
  type ReviewPointKey,
} from "../../api/storyPipeline";
import { useProject, useUpdateProject } from "../../api/projects";
import { useStaleness } from "../../api/staleness";
import { formatDateTime } from "../../format";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ReviewPointPanel } from "./ReviewPointPanel";

type StoryPipelinePanelProps = {
  projectId: number;
};

const STEP_STATUS: Record<
  PipelineStepProgress["status"],
  { label: string; color: string }
> = {
  pending: { label: "Waiting", color: "gray" },
  running: { label: "Running", color: "blue" },
  done: { label: "Done", color: "green" },
  skipped: { label: "Up to date", color: "teal" },
  failed: { label: "Problem", color: "red" },
};

/**
 * "3 of 12" for a step with several targets, nothing for a step with one (or none yet), and
 * how many a run that regenerates only what is out of date left as they are.
 */
function progressText(step: PipelineStepProgress): string {
  const parts: string[] = [];
  if (step.total > 1) {
    parts.push(`${step.done} of ${step.total}`);
  }
  if (step.left_alone > 0) {
    parts.push(`${step.left_alone} left alone`);
  }
  return parts.join(", ");
}

/**
 * One click from the story's text to the rendered video. The run goes through every stage in
 * order, makes the same jobs the stage buttons make, skips whatever is up to date, and stops
 * when nothing can go on. Before it starts the owner can tick the steps to pause after (none by
 * default), choose the project's review points (saved with the project), and, when it would
 * replace something chosen or written by hand, allow that once. While a run waits at a review
 * point, the review view takes the place of the plain pause.
 */
export function StoryPipelinePanel({ projectId }: StoryPipelinePanelProps) {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useStoryPipeline(projectId);
  const start = useStartStoryPipeline(projectId);
  const resume = useContinueStoryPipeline(projectId);
  const stop = useCancelJob();
  const project = useProject(projectId);
  const saveProject = useUpdateProject(projectId);
  const [pauseAfter, setPauseAfter] = useState<string[]>([]);
  const [showPauses, setShowPauses] = useState(false);
  const [allowOverwrite, setAllowOverwrite] = useState(false);
  const [scope, setScope] = useState<PipelineScope>("all");
  const staleness = useStaleness(projectId);
  const outOfDateCount = staleness.data?.count ?? 0;

  const run = data?.run ?? null;
  const active = isJobActive(run);
  const regenerating = scope === "out_of_date";
  const confirmations =
    (regenerating ? data?.regenerate_confirmations : data?.confirmations) ?? [];
  const needsConsent = confirmations.length > 0 && !allowOverwrite;
  const pausedLabel =
    run?.paused_at != null
      ? (data?.steps.find((step) => step.key === run.paused_at)?.label ??
        run.paused_at)
      : null;

  function startRun() {
    start.mutate(
      { pauseAfter, confirmOverwrite: allowOverwrite, scope },
      { onSuccess: () => setAllowOverwrite(false) },
    );
  }

  function stopRun(jobId: number) {
    stop.mutate(jobId, {
      onSettled: () =>
        void queryClient.invalidateQueries({
          queryKey: storyPipelineKey(projectId),
        }),
    });
  }

  const reviewPoints = project.data?.review_points ?? [];

  function toggleReviewPoint(key: ReviewPointKey, ticked: boolean) {
    // The whole list is saved; the server keeps it in the order of the pipeline.
    saveProject.mutate({
      review_points: ticked
        ? [...reviewPoints, key]
        : reviewPoints.filter((item) => item !== key),
    });
  }

  function togglePause(key: string, ticked: boolean) {
    setPauseAfter((current) =>
      ticked ? [...current, key] : current.filter((item) => item !== key),
    );
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Run the whole story</Title>
            <Text size="sm" c="dimmed">
              Takes the story from its text to a rendered video with one click.
              It runs every stage in order, skips whatever is already up to
              date, and stops when nothing can go on. A failed step is tried up
              to {data?.max_tries ?? 3} times (the paid calls included).
              &quot;Only what is out of date&quot; makes again only what exists
              and is out of date, with what that makes necessary (and the
              render), and leaves everything else as it is. Earlier clips, speech
              and renders stay until a new one replaces them.
            </Text>
          </Stack>
          {!active && (
            <Button
              onClick={startRun}
              loading={start.isPending}
              disabled={
                isLoading ||
                isError ||
                !data?.can_start ||
                needsConsent ||
                (regenerating && outOfDateCount === 0)
              }
              style={{ flexShrink: 0 }}
            >
              {regenerating ? "Regenerate out-of-date" : "Run whole pipeline"}
            </Button>
          )}
          {active && run !== null && (
            <Button
              color="red"
              variant="light"
              onClick={() => stopRun(run.job_id)}
              loading={stop.isPending}
              style={{ flexShrink: 0 }}
            >
              Stop
            </Button>
          )}
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the pipeline">
            {describeError(error)}
          </Alert>
        )}
        {start.isError && (
          <Alert color="red" title="Could not start the pipeline">
            {describeError(start.error)}
          </Alert>
        )}
        {resume.isError && (
          <Alert color="red" title="Could not continue the pipeline">
            {describeError(resume.error)}
          </Alert>
        )}
        {stop.isError && (
          <Alert color="red" title="Could not stop the pipeline">
            {describeError(stop.error)}
          </Alert>
        )}

        {data && !active && !data.can_start && data.start_block !== null && (
          <Text size="sm" c="dimmed">
            {data.start_block}
          </Text>
        )}
        {active && (
          <Text size="xs" c="dimmed">
            Stop cancels the jobs that have not started. A job that is already
            running finishes.
          </Text>
        )}

        {data && !active && (
          <Group gap="xs">
            <SegmentedControl
              size="xs"
              value={scope}
              onChange={(value) => {
                setScope(value as PipelineScope);
                setAllowOverwrite(false);
              }}
              data={[
                { value: "all", label: "Everything" },
                { value: "out_of_date", label: "Only what is out of date" },
              ]}
            />
            {regenerating && (
              <Text size="xs" c="dimmed">
                {outOfDateCount === 0
                  ? "Nothing is out of date."
                  : `${outOfDateCount} out of date (see the list below).`}
              </Text>
            )}
          </Group>
        )}

        {data && !active && data.can_start && (
          <Stack gap="xs">
            <Group gap="xs">
              <Button
                size="compact-xs"
                variant="default"
                onClick={() => setShowPauses((value) => !value)}
              >
                {showPauses ? "Hide the pauses" : "Pause after…"}
              </Button>
              <Text size="xs" c="dimmed">
                {pauseAfter.length === 0
                  ? "Nothing is ticked: the run does not stop to be looked at."
                  : `Pauses after ${pauseAfter.length} ${
                      pauseAfter.length === 1 ? "step" : "steps"
                    }. Continue goes on.`}
              </Text>
            </Group>
            <Collapse expanded={showPauses}>
              <Stack gap={4} pt={4}>
                <Text size="xs" c="dimmed">
                  The run pauses once the ticked step is complete for every
                  character, scene or shot, and only if the run made something
                  in it. Jobs that are running finish while it waits.
                </Text>
                {data.steps.map((step) => (
                  <Checkbox
                    key={step.key}
                    size="xs"
                    label={step.label}
                    checked={pauseAfter.includes(step.key)}
                    onChange={(event) =>
                      togglePause(step.key, event.currentTarget.checked)
                    }
                  />
                ))}
              </Stack>
            </Collapse>
          </Stack>
        )}

        {data && !active && project.data !== undefined && (
          <Stack gap={4}>
            <Text size="sm" fw={600}>
              Review points
            </Text>
            <Text size="xs" c="dimmed">
              Saved with this project. None is on by default. A review point
              stops the run once, after its whole stage is made, so you can look
              at it, edit it, or reject what you want made again. Whatever you
              change goes through the usual out-of-date rules. A run keeps the
              review points it started with.
            </Text>
            {data.review_points.map((point) => (
              <Checkbox
                key={point.key}
                size="xs"
                label={point.label}
                checked={reviewPoints.includes(point.key)}
                disabled={saveProject.isPending}
                onChange={(event) =>
                  toggleReviewPoint(point.key, event.currentTarget.checked)
                }
              />
            ))}
            {saveProject.isError && (
              <Text size="xs" c="red.8">
                {describeError(saveProject.error)}
              </Text>
            )}
          </Stack>
        )}

        {confirmations.length > 0 && !active && (
          <Alert color="yellow" title="This run would replace what you chose or wrote">
            <Stack gap={4}>
              {confirmations.map((item) => (
                <Text key={`${item.step}/${item.target}`} size="sm">
                  {item.step_label}
                  {item.target !== "" ? `: ${item.target}` : ""}. {item.reason}
                </Text>
              ))}
              <Checkbox
                mt="xs"
                label="Allow overwrite"
                checked={allowOverwrite}
                onChange={(event) =>
                  setAllowOverwrite(event.currentTarget.checked)
                }
              />
            </Stack>
          </Alert>
        )}

        {run !== null && (
          <Stack gap="xs">
            <Group gap="xs">
              <Badge variant="outline" color="gray">
                {active ? "Running now" : "Last run"}
              </Badge>
              {run.scope === "out_of_date" && (
                <Badge variant="light" color="orange">
                  Only what is out of date
                </Badge>
              )}
              <JobStatusBadge job={run} />
              <Text size="xs" c="dimmed">
                Started {formatDateTime(run.created_at)}
                {run.jobs_made > 0 ? `, ${run.jobs_made} jobs made` : ""}
              </Text>
            </Group>

            {run.review_at != null && data?.review != null && (
              <ReviewPointPanel
                review={data.review}
                isPending={resume.isPending}
                onContinue={(rejected) => resume.mutate(rejected)}
              />
            )}

            {pausedLabel !== null && (
              <Alert color="blue" title={`Paused after ${pausedLabel.toLowerCase()}`}>
                <Stack gap="xs" align="flex-start">
                  <Text size="sm">
                    Look at what the run has made, then press Continue. Nothing
                    new is started while it waits.
                  </Text>
                  <Button
                    size="xs"
                    onClick={() => resume.mutate([])}
                    loading={resume.isPending}
                  >
                    Continue
                  </Button>
                </Stack>
              </Alert>
            )}

            {run.status === "failed" && run.error !== null && !active && (
              <Alert color="red" title="The run stopped">
                {run.error}
              </Alert>
            )}
            {run.problems.length > 0 && (
              <Stack gap={2}>
                {run.problems.map((problem) => (
                  <Text
                    key={`${problem.step}/${problem.target}`}
                    size="sm"
                    c="red.8"
                  >
                    {problem.step_label}
                    {problem.target !== "" ? `, ${problem.target}` : ""}:{" "}
                    {problem.message}
                  </Text>
                ))}
              </Stack>
            )}
            {run.warnings.map((text) => (
              <Text key={text} size="sm" c="yellow.8">
                {text}
              </Text>
            ))}

            <Stack gap={2}>
              {run.steps.map((step) => {
                const status = STEP_STATUS[step.status];
                return (
                  <Group key={step.key} gap="xs" wrap="nowrap">
                    <Badge
                      variant="light"
                      color={status.color}
                      size="sm"
                      w={92}
                      style={{ flexShrink: 0 }}
                    >
                      {status.label}
                    </Badge>
                    <Text size="sm">{step.label}</Text>
                    <Text size="xs" c="dimmed">
                      {progressText(step)}
                    </Text>
                  </Group>
                );
              })}
            </Stack>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
