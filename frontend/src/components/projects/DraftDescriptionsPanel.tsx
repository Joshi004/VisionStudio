import { useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import { useDraftDescriptions, type ScenesState } from "../../api/scenes";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { llmHost } from "./sceneView";

type DraftDescriptionsPanelProps = {
  project: ProjectDetail;
  data: ScenesState;
  /** The current time in milliseconds since 1970, for the job's elapsed time. */
  now: number;
};

/**
 * "Draft descriptions with AI": one paid call that writes every scene's video prompt (for a clip
 * made from its first frame) and its first frame description. It never writes a last frame
 * description. Text the user wrote is kept. It follows the same rules as the scene proposal:
 * only from a click, with a confirmation. Progress shows by itself.
 */
export function DraftDescriptionsPanel({ project, data, now }: DraftDescriptionsPanelProps) {
  const draft = useDraftDescriptions(project.id);
  // Which button was pressed, while the confirmation is open.
  const [confirming, setConfirming] = useState<{ runAgain: boolean } | null>(null);

  const job = data.description_job;
  const isActive = job !== null && (job.status === "queued" || job.status === "running");
  const blockedReason = data.draft_blocked_reason ?? (isActive ? "A draft is already in progress." : null);
  // Like "Run again" for the proposal: it is offered once a draft has written into the scenes,
  // even if the newest job is a later one that failed.
  const hasDraft = data.scenes.some((scene) => scene.description_job_id !== null);
  const scenesWithFrames = data.scenes.filter(
    (scene) => scene.first_frame !== null || scene.last_frame !== null,
  ).length;
  // A last frame description an earlier AI draft wrote. A new draft clears it in each scene it
  // writes into (the AI no longer writes last frame descriptions). The user's own stay.
  const scenesWithAiLastFrameText = data.scenes.filter(
    (scene) =>
      scene.last_frame_description_source === "ai" && scene.last_frame_description !== null,
  ).length;
  const model = data.description_llm.model;

  function start() {
    if (confirming === null) {
      return;
    }
    draft.mutate({ run_again: confirming.runAgain });
    setConfirming(null);
  }

  return (
    <Stack gap={4}>
      <Group gap="sm" align="center">
        <Button
          size="xs"
          disabled={blockedReason !== null}
          loading={draft.isPending}
          onClick={() => setConfirming({ runAgain: false })}
        >
          Draft descriptions with AI
        </Button>
        {hasDraft && (
          <Button
            size="xs"
            variant="default"
            disabled={blockedReason !== null}
            loading={draft.isPending}
            onClick={() => setConfirming({ runAgain: true })}
          >
            Draft again
          </Button>
        )}
        {blockedReason !== null && (
          <Text size="xs" c="dimmed">
            {blockedReason}
          </Text>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        Writes the video prompt and the first frame description of{" "}
        {data.draftable_count} {data.draftable_count === 1 ? "scene" : "scenes"} with {model} at{" "}
        {llmHost(data.description_llm.will_call)}: a paid call that sends your script. Text you
        wrote is kept. Draft descriptions reuses the stored answer when nothing has changed. Draft
        again always asks the model again.
      </Text>

      {draft.isError && (
        <Alert color="red" title="Drafting was not started">
          {describeError(draft.error)}
        </Alert>
      )}

      {job && (
        <Stack gap={4}>
          <Group gap="sm">
            <JobStatusBadge job={job} />
            <Text size="sm" c="dimmed">
              {elapsedText(job, now)}
            </Text>
            <JobActions job={job} />
          </Group>
          {isActive && (
            <Text size="xs" c="dimmed">
              A draft takes 1 to 5 minutes. This updates by itself.
            </Text>
          )}
        </Stack>
      )}

      {job?.status === "failed" && job.error && (
        <Alert color="red" title="Drafting failed">
          <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {job.error}
          </Text>
        </Alert>
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
            Writes the video prompt and the first frame description of {data.draftable_count}{" "}
            {data.draftable_count === 1 ? "scene" : "scenes"} with {model}. Descriptions you wrote
            are kept. This is one paid call that sends your script and its scenes.
          </Text>
          {confirming?.runAgain && (
            <Text size="sm">Drafts the AI wrote earlier are replaced.</Text>
          )}
          {scenesWithAiLastFrameText > 0 && (
            <Text size="sm">
              Last frame descriptions an earlier AI draft wrote are cleared in the scenes it
              rewrites ({scenesWithAiLastFrameText}{" "}
              {scenesWithAiLastFrameText === 1 ? "scene has" : "scenes have"} one). The AI no
              longer writes them, and yours are kept.
            </Text>
          )}
          {scenesWithFrames > 0 && (
            <Alert color="yellow" title="The AI cannot see your frames">
              <Text size="sm">
                {scenesWithFrames} {scenesWithFrames === 1 ? "scene has" : "scenes have"} frames
                already. The model reads the script only, so check that its drafts match them.
              </Text>
            </Alert>
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
