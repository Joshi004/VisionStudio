import {
  Alert,
  Button,
  CopyButton,
  Code,
  Drawer,
  Group,
  Loader,
  Stack,
  Tabs,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJobPrompt, useLabImagePrompt, type JobPrompt } from "../../api/prompts";
import { jobPromptFacts, jobPromptTabs, type PromptTab } from "./promptFormat";

/** What the drawer is asked to show: the prompt of a job, or of a lab picture. */
export type PromptTarget = { job: number } | { image: number };

function TextBlock({ text }: { text: string }) {
  return (
    <Stack gap="xs">
      <Group justify="flex-end">
        <CopyButton value={text}>
          {({ copied, copy }) => (
            <Button size="compact-xs" variant="default" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </Button>
          )}
        </CopyButton>
      </Group>
      <Code block style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "60vh", overflow: "auto" }}>
        {text}
      </Code>
    </Stack>
  );
}

function Tabbed({ tabs }: { tabs: PromptTab[] }) {
  if (tabs.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No model was asked for this version, so there is no prompt.
      </Text>
    );
  }
  return (
    <Tabs defaultValue={tabs[0].id} keepMounted={false}>
      <Tabs.List>
        {tabs.map((tab) => (
          <Tabs.Tab key={tab.id} value={tab.id}>
            {tab.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {tabs.map((tab) => (
        <Tabs.Panel key={tab.id} value={tab.id} pt="sm">
          <TextBlock text={tab.text} />
        </Tabs.Panel>
      ))}
    </Tabs>
  );
}

function JobBody({ prompt }: { prompt: JobPrompt }) {
  const facts = jobPromptFacts(prompt);
  return (
    <Stack gap="sm">
      {facts.length > 0 && (
        <Text size="xs" c="dimmed">
          {facts.join(" · ")}
        </Text>
      )}
      {prompt.feedback && (
        <Alert color="blue" title="Your feedback was part of this request">
          <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {prompt.feedback}
          </Text>
        </Alert>
      )}
      <Tabbed tabs={jobPromptTabs(prompt)} />
    </Stack>
  );
}

function JobContent({ jobId }: { jobId: number }) {
  const { data, isLoading, isError, error } = useJobPrompt(jobId);
  if (isLoading) return <Loader size="sm" />;
  if (isError || !data) {
    return (
      <Alert color="red" title="Could not load the prompt">
        {describeError(error)}
      </Alert>
    );
  }
  return <JobBody prompt={data} />;
}

function ImageContent({ imageId }: { imageId: number }) {
  const { data, isLoading, isError, error } = useLabImagePrompt(imageId);
  if (isLoading) return <Loader size="sm" />;
  if (isError || !data) {
    return (
      <Alert color="red" title="Could not load the prompt">
        {describeError(error)}
      </Alert>
    );
  }
  const facts = [data.model, data.seed !== null ? `seed ${data.seed}` : null].filter(Boolean);
  return (
    <Stack gap="sm">
      {facts.length > 0 && (
        <Text size="xs" c="dimmed">
          {facts.join(" · ")}
        </Text>
      )}
      <Tabbed tabs={data.prompt ? [{ id: "prompt", label: "Prompt", text: data.prompt }] : []} />
    </Stack>
  );
}

/**
 * The whole prompt behind a version on the right of the page (PHASE-038): the instructions, the
 * input and the answer of a language-model call, or the prompt sent to a video or image model.
 * It only shows what the job stored. The hover card (`PromptHoverCard`) opens it.
 */
export function PromptDrawer({
  target,
  onClose,
}: {
  target: PromptTarget | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      opened={target !== null}
      onClose={onClose}
      position="right"
      size="xl"
      title="Prompt behind this version"
    >
      {target !== null && "job" in target && <JobContent jobId={target.job} />}
      {target !== null && "image" in target && <ImageContent imageId={target.image} />}
    </Drawer>
  );
}
