import { useState } from "react";
import { Button, Group, Menu, Modal, Stack, Text } from "@mantine/core";

import { ApiError, describeError } from "../../api/errors";
import { useRunScene, useStoryPipelineState } from "../../api/storyPipeline";

type RunSceneButtonProps = {
  projectId: number;
  sceneId: string;
  /** How the scene is named in the questions, for example "Scene 3: The cellar". */
  sceneLabel: string;
};

/** What the dialog is asking or telling about. */
type Question =
  | { kind: "remake"; stepKey: string; stepLabel: string }
  // The server refused because the run would replace what the owner chose or wrote.
  | { kind: "consent"; remakeFrom: string | null; message: string }
  | { kind: "error"; message: string };

/**
 * "Run this scene" on a scene's own buttons (SCN-004): one click makes or remakes the scene from
 * start to finish (only its own targets, plus whatever story-wide work is missing), ends with a
 * render of the scene, and puts the scene at the front of the GPU server's queue. The menu can
 * also make the scene again from one step, although it is up to date; that asks first, because
 * it spends model calls and GPU time. A run that would replace what the owner wrote asks once
 * more, with the server's own message.
 */
export function RunSceneButton({
  projectId,
  sceneId,
  sceneLabel,
}: RunSceneButtonProps) {
  const pipeline = useStoryPipelineState(projectId).data;
  const run = useRunScene(projectId);
  const [question, setQuestion] = useState<Question | null>(null);

  const blocked =
    pipeline === undefined
      ? "Loading..."
      : pipeline.can_start
        ? null
        : (pipeline.start_block ?? "A run cannot start now.");

  function start(remakeFrom: string | null, confirmOverwrite: boolean) {
    run.mutate(
      { sceneId, remakeFrom, confirmOverwrite },
      {
        onSuccess: () => setQuestion(null),
        onError: (error) =>
          setQuestion(
            error instanceof ApiError && error.status === 409
              ? { kind: "consent", remakeFrom, message: error.message }
              : { kind: "error", message: describeError(error) },
          ),
      },
    );
  }

  return (
    <>
      <Menu position="bottom-end" withinPortal>
        <Menu.Target>
          <Button
            size="compact-sm"
            variant="default"
            loading={run.isPending}
            disabled={blocked !== null}
            title={
              blocked ??
              "Makes what this scene is missing or has out of date, renders the scene and puts it at the front of the GPU queue. Opens a menu to make it again from a step."
            }
          >
            Run this scene
          </Button>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item onClick={() => start(null, false)}>
            Run this scene
            <Text size="xs" c="dimmed">
              Only what is missing or out of date
            </Text>
          </Menu.Item>
          <Menu.Label>Make again from…</Menu.Label>
          {(pipeline?.remake_steps ?? []).map((step) => (
            <Menu.Item
              key={step.key}
              onClick={() =>
                setQuestion({
                  kind: "remake",
                  stepKey: step.key,
                  stepLabel: step.label,
                })
              }
            >
              {step.label}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>

      <Modal
        opened={question !== null}
        onClose={() => setQuestion(null)}
        title={
          question?.kind === "remake"
            ? `Make ${sceneLabel} again?`
            : question?.kind === "consent"
              ? "This would replace what you wrote"
              : "Could not run the scene"
        }
        centered
      >
        {question?.kind === "remake" && (
          <Stack gap="sm">
            <Text size="sm">
              {sceneLabel} is made again from the step “{question.stepLabel}”:
              every target of this scene in that step gets a new version, then
              everything after it that this makes out of date is made again,
              and the scene is rendered. The language model (paid calls) and the
              GPUs are used for it. Earlier clips and renders stay until new
              ones replace them.
            </Text>
            <Group justify="flex-end" gap="xs">
              <Button variant="default" onClick={() => setQuestion(null)}>
                Cancel
              </Button>
              <Button
                loading={run.isPending}
                onClick={() => start(question.stepKey, false)}
              >
                Make it again
              </Button>
            </Group>
          </Stack>
        )}
        {question?.kind === "consent" && (
          <Stack gap="sm">
            <Text size="sm">{question.message}</Text>
            <Group justify="flex-end" gap="xs">
              <Button variant="default" onClick={() => setQuestion(null)}>
                Cancel
              </Button>
              <Button
                color="red"
                loading={run.isPending}
                onClick={() => start(question.remakeFrom, true)}
              >
                Allow overwrite and run
              </Button>
            </Group>
          </Stack>
        )}
        {question?.kind === "error" && (
          <Stack gap="sm">
            <Text size="sm">{question.message}</Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setQuestion(null)}>
                Close
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
