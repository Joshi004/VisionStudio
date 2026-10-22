import { useState, type ReactNode } from "react";
import { Button, Code, HoverCard, Loader, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJobPrompt, useLabImagePrompt, type JobPrompt } from "../../api/prompts";
import { PromptDrawer, type PromptTarget } from "./PromptDrawer";
import { blockTitles, excerpt, inputOf, instructionsOf, jobPromptFacts } from "./promptFormat";

const EXCERPT_STYLE = { whiteSpace: "pre-wrap", wordBreak: "break-word" } as const;

function Excerpt({ label, text, max }: { label: string; text: string; max: number }) {
  if (!text.trim()) return null;
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Code block style={EXCERPT_STYLE}>
        {excerpt(text, max)}
      </Code>
    </Stack>
  );
}

function JobSummary({ prompt }: { prompt: JobPrompt }) {
  if (prompt.kind === "none") {
    return (
      <Text size="sm" c="dimmed">
        No model was asked for this version.
      </Text>
    );
  }
  const facts = jobPromptFacts(prompt);
  const blocks = prompt.kind === "llm" ? blockTitles(inputOf(prompt)) : [];
  return (
    <Stack gap="xs">
      {facts.length > 0 && (
        <Text size="xs" c="dimmed">
          {facts.join(" · ")}
        </Text>
      )}
      {prompt.feedback && (
        <Excerpt label="Your feedback was part of the request" text={prompt.feedback} max={300} />
      )}
      {blocks.length > 0 && (
        <Text size="xs" c="dimmed">
          Sent: {blocks.join(" · ")}
        </Text>
      )}
      {prompt.kind === "llm" ? (
        <Excerpt label="Instructions" text={instructionsOf(prompt)} max={420} />
      ) : (
        <Excerpt label="Prompt" text={prompt.media?.prompt ?? ""} max={700} />
      )}
    </Stack>
  );
}

function JobSummaryLoader({ jobId }: { jobId: number }) {
  const { data, isLoading, isError, error } = useJobPrompt(jobId);
  if (isLoading) return <Loader size="xs" />;
  if (isError || !data) {
    return (
      <Text size="sm" c="red">
        {describeError(error)}
      </Text>
    );
  }
  return <JobSummary prompt={data} />;
}

function ImageSummaryLoader({ imageId }: { imageId: number }) {
  const { data, isLoading, isError, error } = useLabImagePrompt(imageId);
  if (isLoading) return <Loader size="xs" />;
  if (isError || !data) {
    return (
      <Text size="sm" c="red">
        {describeError(error)}
      </Text>
    );
  }
  if (!data.prompt) {
    return (
      <Text size="sm" c="dimmed">
        This picture was uploaded, so no prompt made it.
      </Text>
    );
  }
  const facts = [data.model, data.seed !== null ? `seed ${data.seed}` : null].filter(Boolean);
  return (
    <Stack gap="xs">
      {facts.length > 0 && (
        <Text size="xs" c="dimmed">
          {facts.join(" · ")}
        </Text>
      )}
      <Excerpt label="Prompt" text={data.prompt} max={700} />
    </Stack>
  );
}

type PromptHoverCardProps = {
  /** The job that made the version. Null when no job did. */
  jobId?: number | null;
  /** Instead of a job: the lab picture whose prompt to show. */
  imageId?: number | null;
  /** Who made the version. A manual one was written by the user, with no prompt. */
  source?: "ai" | "manual";
  /** What to say when no job made it and the user did not (code or a fixed rule did). */
  codeNote?: string;
  /** True when what the pointer rests on fills its row (a picture), not just its own width. */
  block?: boolean;
  /** What the pointer rests on. */
  children: ReactNode;
};

/**
 * Hover over a version, a take or a picture to read the prompt that made it (PHASE-038). The
 * card loads the prompt only when it opens, and **Open full prompt** shows all of it. A version
 * the user wrote, or one that code made, says so instead.
 */
export function PromptHoverCard({
  jobId = null,
  imageId = null,
  source = "ai",
  codeNote = "Made by code. No model was asked.",
  block = false,
  children,
}: PromptHoverCardProps) {
  const [drawer, setDrawer] = useState<PromptTarget | null>(null);
  let target: PromptTarget | null = null;
  if (source !== "manual") {
    if (imageId !== null) target = { image: imageId };
    else if (jobId !== null) target = { job: jobId };
  }

  return (
    <>
      <HoverCard
        width={440}
        shadow="md"
        withArrow
        openDelay={250}
        closeDelay={150}
        position="bottom-start"
      >
        <HoverCard.Target>
          <span style={{ display: block ? "block" : "inline-flex" }}>{children}</span>
        </HoverCard.Target>
        <HoverCard.Dropdown>
          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Prompt behind this version
            </Text>
            {source === "manual" && (
              <Text size="sm" c="dimmed">
                Written by you. No model was asked: this version is your own edit.
              </Text>
            )}
            {source !== "manual" && target === null && (
              <Text size="sm" c="dimmed">
                {codeNote}
              </Text>
            )}
            {target !== null && "job" in target && <JobSummaryLoader jobId={target.job} />}
            {target !== null && "image" in target && <ImageSummaryLoader imageId={target.image} />}
            {target !== null && (
              <Button size="compact-xs" variant="light" onClick={() => setDrawer(target)}>
                Open full prompt
              </Button>
            )}
          </Stack>
        </HoverCard.Dropdown>
      </HoverCard>
      <PromptDrawer target={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}
