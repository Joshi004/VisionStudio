import { useState } from "react";
import { Alert, Button, Group, Paper, Select, Stack, Text, Textarea } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJob } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import { useCreatePromptDraft } from "../../api/videoLab";
import { useNow } from "../../hooks/useNow";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { MAX_SHOTS, MIN_SHOTS } from "./labPromptHints";

const SHOT_CHOICES = Array.from({ length: MAX_SHOTS - MIN_SHOTS + 1 }, (_, index) => {
  const shots = MIN_SHOTS + index;
  return { value: String(shots), label: `${shots} shots` };
});

type PromptHelperProps = {
  /** The clip's length in seconds, or null while the form's length box is not a number. */
  durationS: number | null;
  /** Whether the clip starts from a first frame (the writer then continues from it). */
  hasFirstFrame: boolean;
  /** Puts the written prompt into the form. */
  onUse: (prompt: string) => void;
};

/** What the finished job says (`job.output` is stored JSON, so it is read defensively). */
function readOutput(output: unknown): { prompt: string; warnings: string[] } | null {
  if (typeof output !== "object" || output === null) {
    return null;
  }
  const record = output as Record<string, unknown>;
  if (typeof record.prompt !== "string") {
    return null;
  }
  const warnings = Array.isArray(record.warnings)
    ? record.warnings.filter((item): item is string => typeof item === "string")
    : [];
  return { prompt: record.prompt, warnings };
}

/**
 * Writes a multi-shot prompt for LTX-2.5 from a short idea, with a language model. It is a
 * paid call, so it runs only when the button is pressed, and the prompt is not put into the
 * form until you choose to use it: nothing you typed is overwritten.
 */
export function PromptHelper({ durationS, hasFirstFrame, onUse }: PromptHelperProps) {
  const [idea, setIdea] = useState("");
  const [shots, setShots] = useState<string>("3");
  const [note, setNote] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const draft = useCreatePromptDraft();
  const job = useJob(jobId);

  const current = job.data;
  const active = isJobActive(current) || draft.isPending;
  const now = useNow(active, job.dataUpdatedAt);
  const result = current?.status === "succeeded" ? readOutput(current.output) : null;
  const canWrite = idea.trim() !== "" && durationS !== null && !active;

  function write() {
    if (durationS === null) {
      return;
    }
    draft.mutate(
      {
        idea,
        shots: Number(shots),
        duration_s: durationS,
        first_frame_note: hasFirstFrame && note.trim() !== "" ? note : null,
      },
      { onSuccess: (created) => setJobId(created.id) },
    );
  }

  return (
    <Paper withBorder p="sm" radius="md" bg="var(--mantine-color-gray-0)">
      <Stack gap="sm">
        <Stack gap={2}>
          <Text size="sm" fw={600}>
            Write a multi-shot prompt with AI
          </Text>
          <Text size="xs" c="dimmed">
            Give a short idea and the number of shots. The language model writes one paragraph
            that names every cut, which is the only way LTX-2.5 cuts between shots. It is a paid
            call to the language model, made only when you press the button.
          </Text>
        </Stack>

        <Textarea
          label="Idea"
          placeholder="An old fisherman mends his net on the pier at dawn, until something tugs the line."
          value={idea}
          onChange={(event) => setIdea(event.currentTarget.value)}
          maxLength={2000}
          autosize
          minRows={2}
        />
        <Group align="flex-start" grow>
          <Select
            label="Shots"
            description={
              durationS === null
                ? undefined
                : `${(durationS / Number(shots)).toFixed(1)} seconds a shot at ${durationS} seconds`
            }
            data={SHOT_CHOICES}
            value={shots}
            onChange={(value) => value !== null && setShots(value)}
            allowDeselect={false}
          />
          {hasFirstFrame && (
            <Textarea
              label="What the first frame shows"
              description="So the first shot continues from it."
              placeholder="A grey harbour at dawn, a man on a pier."
              value={note}
              onChange={(event) => setNote(event.currentTarget.value)}
              maxLength={1000}
              autosize
              minRows={1}
            />
          )}
        </Group>

        <Group gap="sm">
          <Button onClick={write} disabled={!canWrite} loading={draft.isPending}>
            Write the prompt
          </Button>
          {current && (
            <Group gap="xs">
              <JobStatusBadge job={current} />
              <Text size="sm" c="dimmed">
                {elapsedText(current, now)}
              </Text>
            </Group>
          )}
        </Group>

        {draft.isError && (
          <Alert color="red" title="The prompt was not started">
            {describeError(draft.error)}
          </Alert>
        )}
        {current?.status === "failed" && current.error && (
          <Alert color="red" title="The prompt could not be written">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {current.error}
            </Text>
          </Alert>
        )}

        {result && (
          <Stack gap="xs">
            <Text
              size="sm"
              p="xs"
              style={{
                border: "1px solid var(--mantine-color-gray-3)",
                borderRadius: 6,
                background: "white",
                whiteSpace: "pre-wrap",
              }}
            >
              {result.prompt}
            </Text>
            {result.warnings.map((warning) => (
              <Text key={warning} size="xs" c="orange.8">
                {warning}
              </Text>
            ))}
            <Group gap="sm">
              <Button size="compact-sm" onClick={() => onUse(result.prompt)}>
                Use this prompt
              </Button>
              <Text size="xs" c="dimmed">
                It replaces the prompt in the form. Pressing Write the prompt again makes a new
                one.
              </Text>
            </Group>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
