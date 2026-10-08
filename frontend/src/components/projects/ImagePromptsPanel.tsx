import { useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useWriteImagePrompts } from "../../api/imagePrompts";
import type { ProjectDetail } from "../../api/projects";
import type { ScenesState } from "../../api/scenes";
import {
  hasActiveImagePromptJob,
  hasImagePrompt,
  imagePromptCounts,
  imagePromptCountsLine,
} from "./imagePromptView";
import { llmHost } from "./sceneView";

type ImagePromptsPanelProps = {
  project: ProjectDetail;
  data: ScenesState;
};

/**
 * "Write image prompts": one paid call to the language model for every scene that needs a
 * detailed prompt for its first frame (none yet, or an AI prompt that is out of date). Prompts
 * the user wrote are kept. It follows the same rules as the scene proposal and the drafts: only
 * from a click, with a confirmation that shows the number of calls. Progress shows by itself.
 * Each scene's job and status are in the scenes table and in the scene's drawer.
 */
export function ImagePromptsPanel({ project, data }: ImagePromptsPanelProps) {
  const write = useWriteImagePrompts(project.id);
  const [confirming, setConfirming] = useState(false);

  const blockedReason = data.image_prompts_blocked_reason;
  const count = data.image_prompt_candidate_count;
  const model = data.image_prompt_llm.model;
  const counts = imagePromptCounts(data.scenes);
  // AI prompts that are out of date and would be written again.
  const replacing = data.scenes.filter(
    (scene) =>
      hasImagePrompt(scene) && scene.image_prompt_out_of_date && !hasActiveImagePromptJob(scene),
  ).length;

  function start() {
    write.mutate();
    setConfirming(false);
  }

  return (
    <Stack gap={4}>
      <Group gap="sm" align="center">
        <Button
          size="xs"
          disabled={blockedReason !== null}
          loading={write.isPending}
          onClick={() => setConfirming(true)}
        >
          Write image prompts ({count})
        </Button>
        {blockedReason !== null && (
          <Text size="xs" c="dimmed">
            {blockedReason}
          </Text>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        Writes a detailed prompt for the first frame of {count} {count === 1 ? "scene" : "scenes"}{" "}
        with {model} at {llmHost(data.image_prompt_llm.will_call)}: one paid call for each scene,
        sending its descriptions and narration. Prompts you wrote are kept. A scene whose inputs
        are unchanged reuses its stored answer, with no call.
      </Text>
      <Text size="xs" c="dimmed">
        {imagePromptCountsLine(counts, data.scenes.length)}
        {counts.writing > 0 ? ". This updates by itself." : ""}
      </Text>

      {write.isError && (
        <Alert color="red" title="The image prompts were not started">
          {describeError(write.error)}
        </Alert>
      )}
      {write.isSuccess && (
        <Text size="xs" c="dimmed">
          {write.data.created === 0
            ? "No image prompt needed to start."
            : `Started ${write.data.created} image ${write.data.created === 1 ? "prompt" : "prompts"}. This updates by itself.`}
        </Text>
      )}

      <Modal
        opened={confirming}
        onClose={() => setConfirming(false)}
        title="Before the language model is called"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Writes the image prompts of {count} {count === 1 ? "scene" : "scenes"} with {model}:
            up to {count} paid {count === 1 ? "call" : "calls"}, one for each scene. A stored
            answer is reused, with no call, when a scene's inputs are unchanged. Prompts you wrote
            are kept.
          </Text>
          {replacing > 0 && (
            <Text size="sm">
              {replacing} of these {replacing === 1 ? "replaces" : "replace"} an AI prompt that is
              out of date.
            </Text>
          )}
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
