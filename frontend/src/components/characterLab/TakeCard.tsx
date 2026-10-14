import { useState } from "react";
import { Accordion, Alert, Badge, Button, Group, Paper, Stack, Text, Textarea } from "@mantine/core";

import {
  failedStepJob,
  takeStatus,
  useContinueTake,
  useRerunTake,
  type CharacterTake,
  type TakeStatus,
} from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { formatDateTime } from "../../format";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import {
  changedPrompts,
  PROMPT_HINTS,
  PROMPT_LABELS,
  PROMPT_LIMITS,
  promptDraftsFrom,
  promptKeys,
  rerunProblem,
  STEP_LABELS,
  takeSteps,
  takeSummary,
  type PromptDrafts,
  type PromptKey,
  type StepState,
} from "./characterLabView";

const STATUS_BADGES: Record<TakeStatus, { label: string; color: string }> = {
  running: { label: "running", color: "blue" },
  failed: { label: "failed", color: "red" },
  waiting: { label: "waiting", color: "gray" },
  done: { label: "done", color: "green" },
};

const STEP_STATE_TEXT: Record<StepState, string> = {
  done: "done",
  running: "running",
  failed: "failed",
  todo: "not started",
};

/** What a finished take made, and the pieces of a take that is still being made. */
function Result({ take }: { take: CharacterTake }) {
  const picture = take.image?.url ?? null;
  const speech = take.voice?.url ?? null;
  const clip = take.video?.url ?? null;

  if (take.output === "video" && clip !== null) {
    return (
      // Keyed by the run, so another take always loads fresh.
      <video
        key={take.video?.run_id}
        src={clip}
        controls
        preload="metadata"
        playsInline
        style={{ width: "100%", maxHeight: 460, background: "#000" }}
      />
    );
  }
  return (
    <Stack gap={6}>
      {picture !== null && (
        <img
          key={take.image?.run_id}
          src={picture}
          alt="The picture made for this take"
          loading="lazy"
          style={{
            maxWidth: "100%",
            maxHeight: take.output === "image" ? 460 : 200,
            objectFit: "contain",
            background: "var(--mantine-color-gray-1)",
            borderRadius: 4,
            alignSelf: "flex-start",
          }}
        />
      )}
      {speech !== null && (
        <audio key={take.voice?.run_id} src={speech} controls preload="metadata" style={{ width: "100%" }} />
      )}
    </Stack>
  );
}

/**
 * The prompts the language model wrote, editable. "Run again" sends only the ones that were
 * changed: the server then makes again exactly what depends on them (a new video prompt reuses
 * the same picture and speech).
 */
function PromptEditor({ take, running }: { take: CharacterTake; running: boolean }) {
  const rerun = useRerunTake();
  const stored = promptDraftsFrom(take);
  const keys = promptKeys(take);
  // Only what was typed here: anything else follows the take, so a prompt that is written a
  // moment later still appears.
  const [edited, setEdited] = useState<PromptDrafts>({});
  const drafts: PromptDrafts = { ...stored, ...edited };
  const problem = rerunProblem(take, drafts);
  const written = keys.some((key) => (stored[key] ?? "").trim() !== "");

  if (!written) {
    return (
      <Text size="sm" c="dimmed">
        The prompts are not written yet.
      </Text>
    );
  }

  function edit(key: PromptKey, value: string) {
    rerun.reset();
    setEdited((current) => ({ ...current, [key]: value }));
  }

  return (
    <Stack gap="sm">
      {keys.map((key) => (
        <Textarea
          key={key}
          label={PROMPT_LABELS[key]}
          description={`${PROMPT_HINTS[key]} ${(drafts[key] ?? "").length} of ${PROMPT_LIMITS[key]} characters.`}
          value={drafts[key] ?? ""}
          onChange={(event) => edit(key, event.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={10}
        />
      ))}
      <Group gap="sm">
        <Button
          size="compact-sm"
          loading={rerun.isPending}
          disabled={running || problem !== null}
          onClick={() =>
            rerun.mutate(
              { takeId: take.id, body: changedPrompts(take, drafts) },
              { onSuccess: () => setEdited({}) },
            )
          }
        >
          Run again
        </Button>
        {running ? (
          <Text size="xs" c="dimmed">
            Wait for the running step to finish.
          </Text>
        ) : (
          <Text size="xs" c="dimmed">
            Only what depends on a changed prompt is made again, and it is paid for again.
          </Text>
        )}
      </Group>
      {rerun.isError && (
        <Alert color="red" p="xs" title="Nothing was started">
          {describeError(rerun.error)}
        </Alert>
      )}
    </Stack>
  );
}

/**
 * One thing made with a character. It shows each step (the prompts, the picture, the speech,
 * the video) with its own job, the result when there is one, and, under Advanced, the prompts
 * the language model wrote, which can be edited and run again.
 */
export function TakeCard({ take, now }: { take: CharacterTake; now: number }) {
  const status = takeStatus(take);
  const badge = STATUS_BADGES[status];
  const steps = takeSteps(take);
  const failedJob = failedStepJob(take);
  const next = take.next_step;
  const proceed = useContinueTake();

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <Badge variant="light" color={badge.color}>
                {badge.label}
              </Badge>
              <Text size="sm" fw={600}>
                {takeSummary(take)}
              </Text>
            </Group>
            <Text size="xs" c="dimmed">
              {formatDateTime(take.created_at)}
            </Text>
          </Stack>
        </Group>

        {take.action !== null && (
          <Text size="sm">
            <Text span fw={500}>
              What happens:{" "}
            </Text>
            {take.action}
          </Text>
        )}
        {take.dialogue !== null && take.dialogue.trim() !== "" && (
          <Text size="sm">
            <Text span fw={500}>
              Says:{" "}
            </Text>
            {take.dialogue}
          </Text>
        )}

        <Stack gap={4}>
          {steps.map((row) => (
            <Group key={row.step} gap="xs" wrap="nowrap" justify="space-between" align="flex-start">
              <Group gap="xs" wrap="wrap">
                <Text size="sm" fw={500} w={140}>
                  {STEP_LABELS[row.step]}
                </Text>
                {row.job !== null ? (
                  <>
                    <JobStatusBadge job={row.job} />
                    <Text size="xs" c="dimmed">
                      {elapsedText(row.job, now)}
                    </Text>
                  </>
                ) : (
                  <Text size="xs" c="dimmed">
                    {STEP_STATE_TEXT[row.state]}
                  </Text>
                )}
              </Group>
              {row.job !== null && <JobActions job={row.job} />}
            </Group>
          ))}
        </Stack>

        {status === "failed" && (
          <Alert color="red" p="xs" title="This take stopped">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {take.last_error ?? failedJob?.error ?? "A step failed."}
            </Text>
          </Alert>
        )}

        <Result take={take} />

        {status === "running" && (
          <Text size="xs" c="dimmed">
            The next step starts by itself when this one is done. This page updates by itself.
          </Text>
        )}

        {(status === "failed" || status === "waiting") && next !== null && (
          <Stack gap={4} align="flex-start">
            <Button size="compact-sm" loading={proceed.isPending} onClick={() => proceed.mutate(take.id)}>
              {status === "failed" ? `Try ${STEP_LABELS[next].toLowerCase()} again` : `Continue: ${STEP_LABELS[next].toLowerCase()}`}
            </Button>
            <Text size="xs" c="dimmed">
              {status === "waiting"
                ? "Nothing is running. If the next step does not start by itself, press Continue. "
                : ""}
              Each step is a paid call and starts only from a click.
            </Text>
            {proceed.isError && (
              <Alert color="red" p="xs" title="The step was not started">
                {describeError(proceed.error)}
              </Alert>
            )}
          </Stack>
        )}

        <Accordion variant="contained">
          <Accordion.Item value="advanced">
            <Accordion.Control>Advanced</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Text size="xs" c="dimmed">
                  Seed: {take.seed ?? "random"}
                  {take.duration_s !== null ? ` · Length: ${take.duration_s} s` : ""}
                  {take.negative_prompt ? ` · Negative prompt: ${take.negative_prompt}` : ""}
                </Text>
                <PromptEditor take={take} running={status === "running"} />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </Stack>
    </Paper>
  );
}
