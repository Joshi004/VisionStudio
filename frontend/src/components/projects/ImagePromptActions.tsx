import { useState } from "react";
import { Alert, Anchor, Button, Group, Modal, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import { useWriteImagePrompt } from "../../api/imagePrompts";
import type { ProjectDetail } from "../../api/projects";
import type { Scene } from "../../api/scenes";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { hasActiveImagePromptJob, hasImagePrompt } from "./imagePromptView";

type ImagePromptActionsProps = {
  project: ProjectDetail;
  scene: Scene;
  /** The model that writes the prompt, for the confirmation. */
  model: string;
  /**
   * The drawer holds changes that are not saved yet. The prompt is written from the saved
   * texts, so they are saved first.
   */
  edited: boolean;
  /** The current time in milliseconds since 1970, for the elapsed time. */
  now: number;
};

/**
 * Write image prompt (or Write again) for one scene: one paid call to the language model, with
 * a confirmation, then the status of the newest job. Write again asks the model even when the
 * same request was answered before, so it is offered only for a prompt that is current. A prompt
 * the user wrote is never replaced: the server's reason says to clear it first.
 */
export function ImagePromptActions({ project, scene, model, edited, now }: ImagePromptActionsProps) {
  const write = useWriteImagePrompt(project.id);
  // Which button was pressed, while the confirmation is open.
  const [confirming, setConfirming] = useState<{ runAgain: boolean } | null>(null);

  const job = scene.image_prompt_job;
  const active = hasActiveImagePromptJob(scene);
  const current =
    hasImagePrompt(scene) && scene.image_prompt_source === "ai" && !scene.image_prompt_out_of_date;
  // The server's reason first (nothing to work from, or a prompt you wrote), then the two the
  // page knows about itself.
  const blocked =
    scene.image_prompt_blocked_reason ??
    (active ? "An image prompt is already being written." : null) ??
    (edited ? "Save your changes first." : null);

  function start() {
    if (confirming === null) {
      return;
    }
    write.mutate({ sceneId: scene.id, runAgain: confirming.runAgain });
    setConfirming(null);
  }

  return (
    <Stack gap={6}>
      <Group gap="sm" align="center">
        <Button
          size="xs"
          variant="default"
          disabled={blocked !== null}
          loading={write.isPending}
          onClick={() => setConfirming({ runAgain: current })}
        >
          {current ? "Write again" : "Write image prompt"}
        </Button>
        {blocked !== null && (
          <Text size="xs" c="dimmed" style={{ flex: 1 }}>
            {blocked}
          </Text>
        )}
      </Group>

      {write.isError && (
        <Alert color="red" title="The image prompt was not started">
          {describeError(write.error)}
        </Alert>
      )}

      {job !== null && (
        <Stack gap={4}>
          <Group gap="sm">
            <JobStatusBadge job={job} />
            <Text size="sm" c="dimmed">
              {elapsedText(job, now)}
            </Text>
            <JobActions job={job} />
          </Group>
          {active && (
            <Text size="xs" c="dimmed">
              An image prompt takes about 20 seconds. This updates by itself.
            </Text>
          )}
        </Stack>
      )}
      {job?.status === "failed" && job.error && (
        <Alert color="red" title="The image prompt was not written">
          <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {job.error}
          </Text>
        </Alert>
      )}
      {scene.image_prompt_job_id !== null && (
        <Text size="xs" c="dimmed">
          The AI wrote this prompt in job {scene.image_prompt_job_id}. Its exact request and answer
          are on the{" "}
          <Anchor component={Link} to="/activity" size="xs">
            Activity page
          </Anchor>
          .
        </Text>
      )}

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Before the language model is called"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            {confirming?.runAgain
              ? "Asks the model again, even if the same request was answered before. "
              : ""}
            Writes the image prompt of scene {scene.index + 1} with {model}: one paid call that
            sends this scene's descriptions and narration, and the video's style and recurring
            subjects and places.
          </Text>
          {confirming?.runAgain && (
            <Text size="sm">The prompt the AI wrote earlier is replaced.</Text>
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button onClick={start}>Continue</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
