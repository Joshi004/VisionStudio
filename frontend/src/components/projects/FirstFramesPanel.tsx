import { useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useGenerateFirstFrames } from "../../api/firstFrames";
import type { ProjectDetail } from "../../api/projects";
import type { ScenesState } from "../../api/scenes";
import {
  firstFrameCounts,
  firstFrameCountsLine,
  hasActiveFrameJob,
  hasAiFrame,
} from "./firstFrameView";

type FirstFramesPanelProps = {
  project: ProjectDetail;
  data: ScenesState;
};

/**
 * "Generate first frames": one image from the image model, made on the GPU server, for every
 * scene that has a current image prompt and no first frame, or an AI first frame that is out of
 * date. Frames the user uploaded are kept. It only starts from a click, with a confirmation that
 * shows the number of images. Progress shows by itself. Each scene's job and status are in the
 * scenes table and in the scene's drawer.
 */
export function FirstFramesPanel({ project, data }: FirstFramesPanelProps) {
  const generate = useGenerateFirstFrames(project.id);
  const [confirming, setConfirming] = useState(false);

  const blockedReason = data.frames_blocked_reason;
  const count = data.frame_candidate_count;
  const model = data.image_model_label;
  const counts = firstFrameCounts(data.scenes);
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
        Makes the first frame of {count} {count === 1 ? "scene" : "scenes"} with {model} on your
        GPU server: one image for each scene, from its image prompt. Each takes a few minutes.
        Frames you uploaded are kept. Every frame made is kept, and you can go back to an earlier
        one in a scene's inputs.
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
        title="Before the images are made"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            {count} {count === 1 ? "scene" : "scenes"}, {model}, a few minutes each, at most{" "}
            {data.max_parallel_image_generations} at a time on your GPU server. Each image is a new
            GPU job that loads the model first: nothing is reused, and a job that fails is not
            tried again by itself.
          </Text>
          {replacing > 0 && (
            <Text size="sm">
              {replacing} of these {replacing === 1 ? "replaces" : "replace"} an AI frame that is
              out of date. The old frame stays in the list of earlier frames.
            </Text>
          )}
          <Text size="xs" c="dimmed">
            There is no price per image. The exact request and the server's answer are kept on
            each job.
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
