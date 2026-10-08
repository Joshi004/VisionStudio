import { useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useGenerateFirstFrames } from "../../api/firstFrames";
import type { ProjectDetail } from "../../api/projects";
import type { ScenesState } from "../../api/scenes";
import {
  estimatedCost,
  firstFrameCounts,
  firstFrameCountsLine,
  hasActiveFrameJob,
  hasAiFrame,
} from "./firstFrameView";
import { llmHost } from "./sceneView";

type FirstFramesPanelProps = {
  project: ProjectDetail;
  data: ScenesState;
};

/**
 * "Generate first frames": one paid image from the image model for every scene that has a
 * current image prompt and no first frame, or an AI first frame that is out of date. Frames the
 * user uploaded are kept. It follows the same rules as the other paid steps: only from a click,
 * with a confirmation that shows the number of images and the estimated cost. Progress shows
 * by itself. Each scene's job and status are in the scenes table and in the scene's drawer.
 */
export function FirstFramesPanel({ project, data }: FirstFramesPanelProps) {
  const generate = useGenerateFirstFrames(project.id);
  const [confirming, setConfirming] = useState(false);

  const blockedReason = data.frames_blocked_reason;
  const count = data.frame_candidate_count;
  const model = data.image_llm.model;
  const price = data.price_per_image_usd;
  const counts = firstFrameCounts(data.scenes);
  const cost = estimatedCost(count, price);
  // AI frames that are out of date and would be replaced (they stay in the list of earlier
  // frames).
  const replacing = data.scenes.filter(
    (scene) =>
      hasAiFrame(scene) && scene.first_frame_out_of_date && !hasActiveFrameJob(scene),
  ).length;

  function start() {
    generate.mutate();
    setConfirming(false);
  }

  return (
    <Stack gap={4}>
      <Group gap="sm" align="center">
        <Button
          size="xs"
          disabled={blockedReason !== null}
          loading={generate.isPending}
          onClick={() => setConfirming(true)}
        >
          Generate first frames ({count})
        </Button>
        {blockedReason !== null && (
          <Text size="xs" c="dimmed">
            {blockedReason}
          </Text>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        Makes the first frame of {count} {count === 1 ? "scene" : "scenes"} with {model} at{" "}
        {llmHost(data.image_llm.will_call)}: one paid image for each scene, from its image prompt,
        about ${price} each. Frames you uploaded are kept. Every frame made is kept, and you can go
        back to an earlier one in a scene's inputs.
      </Text>
      <Text size="xs" c="dimmed">
        {firstFrameCountsLine(counts, data.scenes.length)}
        {counts.making > 0 ? ". This updates by itself." : ""}
      </Text>

      {generate.isError && (
        <Alert color="red" title="The first frames were not started">
          {describeError(generate.error)}
        </Alert>
      )}
      {generate.isSuccess && (
        <Text size="xs" c="dimmed">
          {generate.data.created === 0
            ? "No first frame needed to start."
            : `Started ${generate.data.created} first ${generate.data.created === 1 ? "frame" : "frames"}. This updates by itself.`}
        </Text>
      )}

      <Modal
        opened={confirming}
        onClose={() => setConfirming(false)}
        title="Before the image model is called"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            {count} {count === 1 ? "scene" : "scenes"} × about ${price} = about {cost}, model{" "}
            {model}, 20 to 50 s each, at most {data.max_parallel_image_generations} at a time. Each
            image is a new paid call: nothing is reused, and a failed call is not retried.
          </Text>
          {replacing > 0 && (
            <Text size="sm">
              {replacing} of these {replacing === 1 ? "replaces" : "replace"} an AI frame that is
              out of date. The old frame stays in the list of earlier frames.
            </Text>
          )}
          <Text size="xs" c="dimmed">
            The estimate is from Bitdeer's price per image. The usage the provider reports is kept
            on each job.
          </Text>
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button onClick={start}>Continue</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
