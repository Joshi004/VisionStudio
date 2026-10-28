import type { ReactNode } from "react";
import { Alert, Badge, Button, Group, Paper, Stack, Text } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";

import { describeError } from "../../api/errors";
import { useCancelJob } from "../../api/jobs";
import { pipelineBoardKey, type PipelineBoard } from "../../api/pipelineBoard";
import { useContinueStoryPipeline } from "../../api/storyPipeline";

type BoardHeaderProps = {
  projectId: number;
  board: PipelineBoard;
  onOpenStep: (key: string) => void;
};

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "3 running, 1 waiting, 2 held" for the counts that are not zero. */
function countsText(board: PipelineBoard): string {
  const parts: string[] = [];
  if (board.running > 0) {
    parts.push(`${board.running} running`);
  }
  if (board.queued > 0) {
    parts.push(`${board.queued} waiting`);
  }
  if (board.paused > 0) {
    parts.push(`${board.paused} held back`);
  }
  return parts.join(", ");
}

/**
 * Where the project stands in one sentence: a run going on, paused or at a review point, work
 * done by hand, or nothing at all (and then what can be started next).
 */
export function BoardHeader({ projectId, board, onOpenStep }: BoardHeaderProps) {
  const queryClient = useQueryClient();
  const stop = useCancelJob();
  const resume = useContinueStoryPipeline(projectId);

  const labelOf = (key: string) => board.steps.find((step) => step.key === key)?.label ?? key;
  const attention = board.steps.filter((step) => step.status === "attention").length;
  const counts = countsText(board);
  const run = board.run;

  function refreshBoard() {
    void queryClient.invalidateQueries({ queryKey: pipelineBoardKey(projectId) });
  }

  function stopRun() {
    if (run !== null) {
      stop.mutate(run.job_id, { onSettled: refreshBoard });
    }
  }

  let headline: string;
  let detail: string | null = counts === "" ? null : counts;
  let actions: ReactNode = null;

  switch (board.mode) {
    case "pipeline_running": {
      const working = board.steps.filter((step) => step.status === "running");
      headline = "Pipeline running";
      if (working.length > 0) {
        detail = working
          .map((step) => (step.total > 1 ? `${step.label} ${step.done} of ${step.total}` : step.label))
          .join(", ");
        if (counts !== "") {
          detail = `${detail}. ${counts}`;
        }
      }
      actions = (
        <Button color="red" variant="light" onClick={stopRun} loading={stop.isPending}>
          Stop
        </Button>
      );
      break;
    }
    case "pipeline_paused": {
      headline = `Paused after ${run?.paused_at != null ? labelOf(run.paused_at) : "a step"}`;
      actions = (
        <Group gap="xs">
          <Button onClick={() => resume.mutate([], { onSettled: refreshBoard })} loading={resume.isPending}>
            Continue
          </Button>
          <Button color="red" variant="light" onClick={stopRun} loading={stop.isPending}>
            Stop
          </Button>
        </Group>
      );
      break;
    }
    case "pipeline_review": {
      headline = "Waiting for your review";
      actions = (
        <Group gap="xs">
          <Button onClick={() => onOpenStep("run")}>Open review</Button>
          <Button color="red" variant="light" onClick={stopRun} loading={stop.isPending}>
            Stop
          </Button>
        </Group>
      );
      break;
    }
    case "manual_running": {
      headline = "Manual work going on";
      break;
    }
    case "idle": {
      const nextKey = board.next_keys[0];
      const allDone = board.steps.every((step) => step.status === "done" || step.status === "off");
      if (nextKey !== undefined) {
        headline = "Nothing running";
        detail = `Next: ${labelOf(nextKey)}${
          board.next_keys.length > 1 ? ` (${plural(board.next_keys.length - 1, "other step", "other steps")} ready too)` : ""
        }`;
        actions = <Button onClick={() => onOpenStep(nextKey)}>Open</Button>;
      } else if (allDone) {
        headline = "Everything is done";
        detail = null;
      } else {
        headline = "Nothing running";
        detail = "No step can be started by hand right now.";
      }
      break;
    }
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="xs">
        <Group justify="space-between" align="center" wrap="nowrap">
          <Stack gap={2}>
            <Group gap="xs">
              <Text fw={600}>{headline}</Text>
              {attention > 0 && (
                <Badge color="red" variant="light">
                  {plural(attention, "step needs attention", "steps need attention")}
                </Badge>
              )}
            </Group>
            {detail !== null && (
              <Text size="sm" c="dimmed">
                {detail}
              </Text>
            )}
          </Stack>
          {actions}
        </Group>
        {stop.isError && (
          <Alert color="red" title="Could not stop the pipeline">
            {describeError(stop.error)}
          </Alert>
        )}
        {resume.isError && (
          <Alert color="red" title="Could not continue the pipeline">
            {describeError(resume.error)}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
