import { useState } from "react";
import { Button, Code, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJobPrompt } from "../../api/prompts";
import type { ShotPromptContent, ShotPromptEntry } from "../../api/shotPrompts";

const CODE_STYLE = { whiteSpace: "pre-wrap", wordBreak: "break-word" } as const;

type ShotPromptVersion = NonNullable<ShotPromptEntry["version"]>;

/** Who wrote a version of the prompt, as one phrase. */
function writtenBy(version: ShotPromptVersion): string {
  if (version.source === "manual") {
    return "edited by you";
  }
  return version.feedback ? "written from your feedback" : "written by the model";
}

/** The prompt an earlier take was generated with, read back from that take's job. */
function PreviousPrompt({ jobId, takeNumber }: { jobId: number; takeNumber: number }) {
  const { data, isLoading, isError, error } = useJobPrompt(jobId);
  if (isLoading) {
    return <Loader size="xs" />;
  }
  if (isError) {
    return (
      <Text size="xs" c="red">
        {describeError(error)}
      </Text>
    );
  }
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">
        The prompt of take {takeNumber}
      </Text>
      <Code block style={CODE_STYLE}>
        {data?.media?.prompt ?? "No prompt was stored for this take."}
      </Code>
    </Stack>
  );
}

type ShotPromptReviewProps = {
  prompt: ShotPromptContent;
  version: ShotPromptVersion;
  /** The take whose clip is on view: it was made before this prompt. */
  take: { number: number; jobId: number | null };
  canGenerate: boolean;
  canRewrite: boolean;
  onGenerate: () => void;
  onFeedback: () => void;
  onEdit: () => void;
};

/**
 * Shown under a shot's clip when its newest prompt is newer than the one the clip was made from.
 * The user reads the new prompt, may compare it with the old one, and then generates with it,
 * writes more feedback, or edits it by hand. Nothing is generated until the user presses.
 */
export function ShotPromptReview({
  prompt,
  version,
  take,
  canGenerate,
  canRewrite,
  onGenerate,
  onFeedback,
  onEdit,
}: ShotPromptReviewProps) {
  const [showPrevious, setShowPrevious] = useState(false);

  return (
    <Paper withBorder p="sm" radius="sm">
      <Stack gap="xs">
        <Text size="sm" fw={500}>
          A newer prompt is ready (version {version.version}, {writtenBy(version)})
        </Text>
        <Text size="xs" c="dimmed">
          The clip above was made from an older prompt. Read the new one, then generate a new
          take with it. Nothing is generated until you press the button.
        </Text>
        <Code block style={CODE_STYLE}>
          {prompt.prompt}
        </Code>
        {take.jobId !== null && (
          <Stack gap={4} align="flex-start">
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={() => setShowPrevious((value) => !value)}
            >
              {showPrevious ? "Hide the previous prompt" : "Show the previous prompt"}
            </Button>
            {showPrevious && <PreviousPrompt jobId={take.jobId} takeNumber={take.number} />}
          </Stack>
        )}
        <Group gap="xs">
          <Button size="compact-sm" disabled={!canGenerate} onClick={onGenerate}>
            Generate with this prompt
          </Button>
          <Button size="compact-sm" variant="default" disabled={!canRewrite} onClick={onFeedback}>
            More feedback
          </Button>
          <Button size="compact-sm" variant="default" disabled={!canRewrite} onClick={onEdit}>
            Edit by hand
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
