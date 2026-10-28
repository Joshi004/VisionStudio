import { useState } from "react";
import {
  Alert,
  Anchor,
  Button,
  Group,
  SegmentedControl,
  Stack,
  Text,
} from "@mantine/core";

import type { PipelineReview, RejectedTarget } from "../../api/storyPipeline";
import { useProjectPanels } from "./projectPanels";

type ReviewPointPanelProps = {
  review: PipelineReview;
  isPending: boolean;
  onContinue: (rejected: RejectedTarget[]) => void;
};

/** One answer per target: the step and the target make its key. */
function answerKey(step: string, target: string): string {
  return JSON.stringify([step, target]);
}

/** Moves the page to the stage panel that shows a step's work (it is opened first). */
function scrollToStep(stepKey: string) {
  document
    .getElementById(`pipeline-step-${stepKey}`)
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Shown while a run waits at a review point. The run has made what the point covers; the
 * owner looks at it in the stage panels below (and may edit it there), approves or rejects
 * each target, and presses Continue. A rejected target is made again, and the run waits here
 * once more so the new result can be looked at. Everything not rejected counts as approved.
 */
export function ReviewPointPanel({
  review,
  isPending,
  onContinue,
}: ReviewPointPanelProps) {
  const [rejected, setRejected] = useState<Record<string, boolean>>({});
  const { openPanel } = useProjectPanels();

  function showStep(stepKey: string) {
    openPanel(stepKey);
    // The panel is rendered by the next frame, so the scroll lands on its final position.
    requestAnimationFrame(() => scrollToStep(stepKey));
  }

  const rejectedTargets: RejectedTarget[] = review.steps.flatMap((step) =>
    step.targets
      .filter((target) => rejected[answerKey(step.key, target.key)] === true)
      .map((target) => ({ step: step.key, target: target.key })),
  );

  function answer(step: string, target: string, reject: boolean) {
    setRejected((current) => ({
      ...current,
      [answerKey(step, target)]: reject,
    }));
  }

  return (
    <Alert color="blue" title={`Review: ${review.label.toLowerCase()}`}>
      <Stack gap="xs">
        <Text size="sm">
          The run has made this stage and is waiting for you. Look at it in the
          panels below and change anything you like: edits follow the usual
          out-of-date rules, and the run reads their result when it continues.
          Reject what you want made again; the run then waits here once more.
          Rejecting something you wrote, or chose from the library, allows it to
          be replaced.
        </Text>

        {review.steps.map((step) => (
          <Stack key={step.key} gap={4}>
            <Text size="sm" fw={600}>
              {step.label}
            </Text>
            {step.targets.length === 0 && (
              <Text size="xs" c="dimmed">
                Nothing was made in this step.
              </Text>
            )}
            {step.targets.map((target) => {
              const isRejected =
                rejected[answerKey(step.key, target.key)] === true;
              return (
                <Group
                  key={target.key}
                  gap="xs"
                  justify="space-between"
                  wrap="nowrap"
                >
                  <Text size="sm">{target.label}</Text>
                  <Group gap="xs" wrap="nowrap">
                    <Anchor
                      component="button"
                      type="button"
                      size="xs"
                      onClick={() => showStep(step.key)}
                    >
                      Show
                    </Anchor>
                    <SegmentedControl
                      size="xs"
                      value={isRejected ? "reject" : "approve"}
                      onChange={(value) =>
                        answer(step.key, target.key, value === "reject")
                      }
                      data={[
                        { value: "approve", label: "Approve" },
                        { value: "reject", label: "Reject" },
                      ]}
                    />
                  </Group>
                </Group>
              );
            })}
          </Stack>
        ))}

        <Group>
          <Button
            size="xs"
            onClick={() => onContinue(rejectedTargets)}
            loading={isPending}
          >
            {rejectedTargets.length === 0
              ? "Continue"
              : `Remake ${rejectedTargets.length} rejected and review again`}
          </Button>
        </Group>
      </Stack>
    </Alert>
  );
}
