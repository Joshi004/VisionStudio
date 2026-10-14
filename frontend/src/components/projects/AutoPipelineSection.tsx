import { useState } from "react";
import {
  Alert,
  Button,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";

import { useAutoGenerate, useStartAutoGenerate } from "../../api/autoPipeline";
import { describeError } from "../../api/errors";
import { useCancelJob } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import type { ProjectDetail } from "../../api/projects";
import { useNow } from "../../hooks/useNow";
import { useRefreshWhenFinished } from "../../hooks/useRefreshWhenFinished";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { problemText, stepDescription, stepMarker } from "./autoPipelineView";

/**
 * Automatic generation: one click runs every step to the final video. The steps are the ones
 * of the sections below. Steps that do not depend on each other go on at the same time, and a
 * scene goes on to its next step as soon as its own input is ready, so several steps can be
 * running at once. A scene that fails is tried again a few times before the run stops, once
 * nothing else can go on, and says what is wrong.
 */
export function AutoPipelineSection({ project }: { project: ProjectDetail }) {
  const query = useAutoGenerate(project.id);
  const start = useStartAutoGenerate(project.id);
  const cancel = useCancelJob();
  const [confirming, setConfirming] = useState(false);

  const data = query.data;
  const job = data?.job ?? null;
  const steps = data?.steps ?? [];
  const problems = data?.problems ?? [];
  const confirmations = data?.confirmations;
  const maxTries = data?.max_tries ?? 3;

  const isActive = isJobActive(job);
  // Elapsed times are worked out from the stored times and the clock, which ticks once a
  // second while the run is waiting or running. When it finishes, the whole page is loaded.
  const now = useNow(isActive, query.dataUpdatedAt);
  useRefreshWhenFinished(isActive);

  const blockedReason = data?.start_blocked_reason ?? null;
  const scenesWithInputs = confirmations?.scenes_with_inputs ?? 0;
  const mismatch = confirmations?.mismatch ?? null;
  const showSteps = job !== null;

  function confirmStart() {
    setConfirming(false);
    start.mutate({
      accept_mismatch: mismatch !== null,
      discard_scenes_with_inputs: scenesWithInputs > 0,
    });
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="center" wrap="nowrap">
          <Title order={4}>Automatic generation</Title>
          {isActive ? (
            <Button
              color="red"
              variant="light"
              loading={cancel.isPending}
              disabled={job === null || !job.can_cancel}
              onClick={() => job !== null && cancel.mutate(job.id)}
            >
              Stop
            </Button>
          ) : (
            <Button
              onClick={() => setConfirming(true)}
              loading={start.isPending}
              disabled={query.isLoading || blockedReason !== null}
            >
              {job === null ? "Start automatic generation" : "Start again"}
            </Button>
          )}
        </Group>

        {blockedReason !== null && !isActive ? (
          <Text size="sm" c="dimmed">
            {blockedReason}
          </Text>
        ) : (
          <Text size="sm" c="dimmed">
            Does every step for you, up to the final video. Steps that do not depend on each other
            run at the same time, and each scene goes on as soon as its own input is ready: its clip
            starts once its frames are made, while other scenes are still making theirs. A scene
            that fails is tried again, up to {maxTries} tries in a step. Steps that are already
            done are skipped.
          </Text>
        )}

        {query.isLoading && <Loader size="sm" />}

        {query.isError && (
          <Alert color="red" title="Could not load the automatic flow">
            {describeError(query.error)} Press Refresh to try again.
          </Alert>
        )}

        {start.isError && (
          <Alert color="red" title="The automatic flow was not started">
            {describeError(start.error)}
          </Alert>
        )}

        {cancel.isError && (
          <Alert color="red" title="The run was not stopped">
            {describeError(cancel.error)}
          </Alert>
        )}

        {job !== null && (
          <Stack gap={4}>
            <Group gap="sm">
              <JobStatusBadge job={job} />
              <Text size="sm" c="dimmed">
                {elapsedText(job, now)}
              </Text>
            </Group>
            {isActive && (
              <Text size="xs" c="dimmed">
                This updates by itself. Stop cancels the jobs that have not started. Jobs already
                running finish on their own.
              </Text>
            )}
          </Stack>
        )}

        {showSteps && (
          // A list, not a stepper: a stepper has one active step, and here several steps run at
          // once, each with its own status.
          <Stack gap={8} aria-label="Steps of the automatic flow">
            {steps.map((step, index) => {
              const marker = stepMarker(step, index + 1);
              const description = stepDescription(step);
              const quiet = step.status === "pending" || step.status === "stopped";
              return (
                <Group key={step.key} gap="sm" wrap="nowrap" align="flex-start">
                  <ThemeIcon
                    size={24}
                    radius="xl"
                    color={marker.color}
                    variant={quiet ? "light" : "filled"}
                  >
                    {step.status === "running" ? (
                      <Loader size={12} color="white" />
                    ) : (
                      <Text size="xs" fw={700} lh={1} c="inherit">
                        {marker.text}
                      </Text>
                    )}
                  </ThemeIcon>
                  <Stack gap={0}>
                    <Text
                      size="sm"
                      fw={step.status === "running" ? 600 : 400}
                      c={step.status === "pending" ? "dimmed" : undefined}
                    >
                      {step.label}
                    </Text>
                    {description !== "" && (
                      <Text size="xs" c="dimmed">
                        {description}
                      </Text>
                    )}
                  </Stack>
                </Group>
              );
            })}
          </Stack>
        )}

        {job?.status === "failed" && (
          <Alert color="red" title="The automatic flow stopped">
            <Stack gap={4}>
              {problems.length > 0 ? (
                problems.map((problem, index) => (
                  <Text
                    key={`${problem.scene_id ?? "project"}-${index}`}
                    size="sm"
                    style={{ wordBreak: "break-word" }}
                  >
                    {problemText(problem)}
                  </Text>
                ))
              ) : (
                <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {job.error}
                </Text>
              )}
              <Text size="sm">
                Fix what is listed (or edit the scene), then press Start again: the steps that are
                done are skipped.
              </Text>
            </Stack>
          </Alert>
        )}

        {isActive && problems.length > 0 && (
          <Alert color="yellow" title="Some work could not be done">
            <Stack gap={4}>
              {problems.map((problem, index) => (
                <Text
                  key={`${problem.scene_id ?? "project"}-${index}`}
                  size="sm"
                  style={{ wordBreak: "break-word" }}
                >
                  {problemText(problem)}
                </Text>
              ))}
              <Text size="sm">
                The rest of the run goes on. It stops when nothing is left to try.
              </Text>
            </Stack>
          </Alert>
        )}
      </Stack>

      <Modal
        opened={confirming}
        onClose={() => setConfirming(false)}
        title="Start automatic generation"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Steps that do not depend on each other run at the same time, and each scene goes on as
            soon as its own input is ready, so several calls to your GPU server and the language
            model run together (up to the limits set on the Settings page). Steps that are already
            done are skipped, and frames you uploaded are never replaced.
          </Text>
          <List type="ordered" size="sm" spacing={2}>
            {steps.map((step) => (
              <List.Item key={step.key}>{step.label}</List.Item>
            ))}
          </List>
          <Alert color="yellow" title="This makes paid calls">
            <Text size="sm">
              The language model (scenes, the characters and places, who is in each scene,
              descriptions, image prompts, last frame prompts) and your GPU server (the reference
              pictures, first frames, last frames, transcription, clips) are called. A scene that
              fails is tried again, up to {maxTries} tries in a step, and each try can be paid. Stopping
              the run does not take back a call that is already running.
            </Text>
          </Alert>
          {mismatch !== null && (
            <Alert color="orange" title="The recording differs from the script">
              <Text size="sm">{mismatch}</Text>
              <Text size="sm">You can fix the script and transcribe again, or go on anyway.</Text>
            </Alert>
          )}
          {scenesWithInputs > 0 && (
            <Alert color="yellow" title="Scenes with inputs will be replaced">
              <Text size="sm">
                {scenesWithInputs} {scenesWithInputs === 1 ? "scene has" : "scenes have"} a
                description, frames or a clip. The flow proposes scenes again, which replaces all
                the scenes and discards those inputs. Their files stay on disk.
              </Text>
            </Alert>
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button onClick={confirmStart}>Start</Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
