import { useState } from "react";
import { Alert, Button, Group, Paper, SegmentedControl, Select, Stack, Text, Textarea } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJob } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import { useCreatePromptDraft } from "../../api/videoLab";
import { useNow } from "../../hooks/useNow";
import { H3_MODEL, type LabVideoModel } from "../../videoModels";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { H3_MAX_SHOTS, H3_MIN_SHOTS, MAX_SHOTS, MIN_SHOTS } from "./labPromptHints";

type PromptFormat = "ltx" | "h3";

/** The numbers of shots a prompt can be written for: MiniMax H3 also takes a single shot. */
function shotChoices(format: PromptFormat) {
  const min = format === "h3" ? H3_MIN_SHOTS : MIN_SHOTS;
  const max = format === "h3" ? H3_MAX_SHOTS : MAX_SHOTS;
  return Array.from({ length: max - min + 1 }, (_, index) => {
    const shots = min + index;
    return { value: String(shots), label: shots === 1 ? "1 shot" : `${shots} shots` };
  });
}

type PromptHelperProps = {
  /** The clip's length in seconds, or null while the form's length box is not a number. */
  durationS: number | null;
  /** Whether the clip starts from a first frame (the writer then continues from it). */
  hasFirstFrame: boolean;
  /** The models the form will run: they decide which prompt formats can be written. */
  models: LabVideoModel[];
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
 * Writes a multi-shot prompt from a short idea, with a language model: one paragraph that names
 * every cut for LTX-2.5, or the three structured fields MiniMax H3 was trained on. It is a paid
 * call, so it runs only when the button is pressed, and the prompt is not put into the form
 * until you choose to use it: nothing you typed is overwritten.
 */
export function PromptHelper({ durationS, hasFirstFrame, models, onUse }: PromptHelperProps) {
  const [idea, setIdea] = useState("");
  const [shots, setShots] = useState<string>("3");
  const [note, setNote] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  // MiniMax H3 is the default model, so its format is the one offered first.
  const [chosenFormat, setChosenFormat] = useState<PromptFormat>("h3");
  const draft = useCreatePromptDraft();
  const job = useJob(jobId);

  const hasH3 = models.includes(H3_MODEL);
  const hasLtx = models.some((model) => model !== H3_MODEL);
  // One format when the form has one kind of model; a choice when it has both.
  const format: PromptFormat = hasH3 && !hasLtx ? "h3" : hasH3 ? chosenFormat : "ltx";
  const choices = shotChoices(format);
  // Switching to LTX can leave a single shot chosen, which LTX cannot cut.
  const shotsValue = choices.some((choice) => choice.value === shots) ? shots : "3";
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
        shots: Number(shotsValue),
        duration_s: durationS,
        first_frame_note: hasFirstFrame && note.trim() !== "" ? note : null,
        target_model: format === "h3" ? H3_MODEL : "ltx-2.5",
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
            {format === "h3"
              ? "Give a short idea and the number of shots. The language model writes the three fields MiniMax H3 was trained on: the [Shot N] blocks with their cut times, the soundscape and the music. When a first or last frame is chosen, the app adds the line that places it when the clip runs. "
              : "Give a short idea and the number of shots. The language model writes one paragraph that names every cut, which is the only way LTX-2.5 cuts between shots. "}
            It is a paid call to the language model, made only when you press the button.
          </Text>
        </Stack>

        {hasH3 && hasLtx && (
          <Stack gap={2}>
            <Text size="sm" fw={500}>
              Write it for
            </Text>
            <SegmentedControl
              value={format}
              onChange={(value) => setChosenFormat(value === "h3" ? "h3" : "ltx")}
              data={[
                { value: "h3", label: "MiniMax H3 (structured)" },
                { value: "ltx", label: "LTX-2.5 (one paragraph)" },
              ]}
            />
            <Text size="xs" c="dimmed">
              The form runs both kinds of model with one prompt. Write it for the one you care
              about, or write each and run them separately.
            </Text>
          </Stack>
        )}

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
                : `${(durationS / Number(shotsValue)).toFixed(1)} seconds a shot at ${durationS} seconds`
            }
            data={choices}
            value={shotsValue}
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
