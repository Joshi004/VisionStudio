import { useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useGenerateLastFrames, useWriteLastFramePrompts } from "../../api/lastFrames";
import type { ProjectDetail } from "../../api/projects";
import type { ScenesState } from "../../api/scenes";
import {
  hasActiveLastFrameJob,
  hasActiveLastFramePromptJob,
  hasAiLastFrame,
  hasLastFramePrompt,
  lastFrameCounts,
  lastFrameCountsLine,
} from "./lastFrameView";
import { llmHost } from "./sceneView";

type LastFramesPanelProps = {
  project: ProjectDetail;
  data: ScenesState;
};

/**
 * Last frames: the AI decides which scenes get one when it drafts the descriptions (a scene whose
 * ending is a visible change inside the same shot), so most scenes get none and this panel shows
 * only when some do. Two buttons, in the order the work goes: "Write last frame prompts" (one
 * paid call to the language model for each scene, the instruction that edits the first frame)
 * and "Generate last frames" (one image from the image model for each scene, made on the GPU
 * server by editing the first frame). Both only start from a click, with a confirmation that
 * shows the number of calls or images. Progress shows by itself. Each scene's jobs and status
 * are in the scenes table and in the scene's drawer.
 */
export function LastFramesPanel({ project, data }: LastFramesPanelProps) {
  const writePrompts = useWriteLastFramePrompts(project.id);
  const generate = useGenerateLastFrames(project.id);
  const [confirmingPrompts, setConfirmingPrompts] = useState(false);
  const [confirmingFrames, setConfirmingFrames] = useState(false);

  const counts = lastFrameCounts(data.scenes);
  if (counts.planned === 0) {
    return null;
  }

  const promptsBlocked = data.last_frame_prompts_blocked_reason;
  const promptCount = data.last_frame_prompt_candidate_count;
  const promptModel = data.image_prompt_llm.model;
  const framesBlocked = data.last_frames_blocked_reason;
  const frameCount = data.last_frame_candidate_count;
  const imageModel = data.image_model_label;
  // AI prompts that are out of date and would be written again, and AI frames that are out of
  // date and would be replaced (they stay in the list of earlier frames).
  const replacingPrompts = data.scenes.filter(
    (scene) =>
      hasLastFramePrompt(scene) &&
      scene.last_frame_prompt_out_of_date &&
      !hasActiveLastFramePromptJob(scene),
  ).length;
  const replacingFrames = data.scenes.filter(
    (scene) => hasAiLastFrame(scene) && scene.last_frame_out_of_date && !hasActiveLastFrameJob(scene),
  ).length;

  function startPrompts() {
    writePrompts.mutate();
    setConfirmingPrompts(false);
  }

  function startFrames() {
    generate.mutate();
    setConfirmingFrames(false);
  }

  return (
    <Stack gap={4}>
      <Group gap="sm" align="center">
        <Button
          size="xs"
          disabled={promptsBlocked !== null}
          loading={writePrompts.isPending}
          onClick={() => setConfirmingPrompts(true)}
        >
          Write last frame prompts ({promptCount})
        </Button>
        <Button
          size="xs"
          disabled={framesBlocked !== null}
          loading={generate.isPending}
          onClick={() => setConfirmingFrames(true)}
        >
          Generate last frames ({frameCount})
        </Button>
      </Group>
      {promptsBlocked !== null && (
        <Text size="xs" c="dimmed">
          Prompts: {promptsBlocked}
        </Text>
      )}
      {framesBlocked !== null && (
        <Text size="xs" c="dimmed">
          Frames: {framesBlocked}
        </Text>
      )}
      <Text size="xs" c="dimmed">
        A last frame pins how a clip ends: the clip moves from the first frame to the last. It is
        made by editing the first frame, so it shows the same shot a moment later. The AI picks
        the scenes that get one; you can write or upload your own. A scene that continues the
        previous scene's action starts on that scene's last frame.
      </Text>
      <Text size="xs" c="dimmed">
        {lastFrameCountsLine(counts)}
        {counts.making + counts.promptsWriting > 0 ? ". This updates by itself." : ""}
      </Text>

      {writePrompts.isError && (
        <Alert color="red" title="The last frame prompts were not started">
          {describeError(writePrompts.error)}
        </Alert>
      )}
      {writePrompts.isSuccess && (
        <Text size="xs" c="dimmed">
          {writePrompts.data.created === 0
            ? "No last frame prompt needed to start."
            : `Started ${writePrompts.data.created} last frame ${writePrompts.data.created === 1 ? "prompt" : "prompts"}. This updates by itself.`}
        </Text>
      )}
      {generate.isError && (
        <Alert color="red" title="The last frames were not started">
          {describeError(generate.error)}
        </Alert>
      )}
      {generate.isSuccess && (
        <Text size="xs" c="dimmed">
          {generate.data.created === 0
            ? "No last frame needed to start."
            : `Started ${generate.data.created} last ${generate.data.created === 1 ? "frame" : "frames"}. This updates by itself.`}
        </Text>
      )}

      <Modal
        opened={confirmingPrompts}
        onClose={() => setConfirmingPrompts(false)}
        title="Before the language model is called"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Writes the last frame prompts of {promptCount} {promptCount === 1 ? "scene" : "scenes"}{" "}
            with {promptModel} at {llmHost(data.image_prompt_llm.will_call)}: up to {promptCount}{" "}
            paid {promptCount === 1 ? "call" : "calls"}, one for each scene. A stored answer is
            reused, with no call, when a scene's inputs are unchanged. Prompts you wrote are kept.
          </Text>
          {replacingPrompts > 0 && (
            <Text size="sm">
              {replacingPrompts} of these {replacingPrompts === 1 ? "replaces" : "replace"} an AI
              prompt that is out of date.
            </Text>
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirmingPrompts(false)}>
              Cancel
            </Button>
            <Button onClick={startPrompts}>Continue</Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={confirmingFrames}
        onClose={() => setConfirmingFrames(false)}
        title="Before the images are made"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            {frameCount} {frameCount === 1 ? "scene" : "scenes"}, {imageModel}, a few minutes each.
            Your GPU server runs at most {data.max_parallel_gpu_jobs} jobs at a time, shared with
            the clips and other GPU work. Each image edits a scene's first frame in a new GPU job
            that loads the model first: nothing is reused, and a job that fails is not tried again
            by itself.
          </Text>
          {replacingFrames > 0 && (
            <Text size="sm">
              {replacingFrames} of these {replacingFrames === 1 ? "replaces" : "replace"} an AI
              frame that is out of date. The old frame stays in the list of earlier frames.
            </Text>
          )}
          <Text size="xs" c="dimmed">
            There is no price per image. The exact request and the server's answer are kept on each
            job.
          </Text>
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirmingFrames(false)}>
              Cancel
            </Button>
            <Button onClick={startFrames}>Continue</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
