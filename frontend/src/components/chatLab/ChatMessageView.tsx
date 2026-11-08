import { useState } from "react";
import { Alert, Badge, Button, Collapse, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import type { ChatMessage, ChatModel } from "../../api/chatLab";
import { describeError } from "../../api/errors";
import { useCancelJob } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import { MarkdownText } from "./MarkdownText";

type ChatMessageViewProps = {
  message: ChatMessage;
  /** Only the last reply can be tried again. */
  isLast: boolean;
  models: ChatModel[];
  retrying: boolean;
  onRetry: (messageId: number) => void;
  /** Called after a waiting reply was cancelled, so the chat is loaded again at once. */
  onCancelled: () => void;
};

function modelLabel(models: ChatModel[], id: string | null): string {
  return models.find((model) => model.id === id)?.label ?? id ?? "";
}

function tokenText(usage: ChatMessage["usage"]): string | null {
  if (!usage) {
    return null;
  }
  const parts: string[] = [];
  if (usage.prompt_tokens != null) {
    parts.push(`${usage.prompt_tokens.toLocaleString()} tokens in`);
  }
  if (usage.completion_tokens != null) {
    parts.push(`${usage.completion_tokens.toLocaleString()} out`);
  }
  if (usage.reasoning_tokens) {
    parts.push(`${usage.reasoning_tokens.toLocaleString()} thinking`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <Group justify="flex-end">
      <Paper withBorder radius="md" p="sm" maw="85%" bg="var(--mantine-color-blue-light)">
        <Text style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{message.content}</Text>
      </Paper>
    </Group>
  );
}

function Thinking({ text, active }: { text: string; active: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <Stack gap={4}>
      <Button
        size="compact-xs"
        variant="subtle"
        color="gray"
        w="fit-content"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Hide thinking" : active ? "Thinking…" : "Show thinking"}
      </Button>
      <Collapse expanded={open}>
        <Text size="sm" c="dimmed" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {text}
        </Text>
      </Collapse>
    </Stack>
  );
}

function AssistantMessage({
  message,
  isLast,
  models,
  retrying,
  onRetry,
  onCancelled,
}: ChatMessageViewProps) {
  const cancel = useCancelJob();
  const job = message.job;
  const active = isJobActive(job);
  const waiting = job?.status === "queued";
  const failed = job?.status === "failed" || job?.status === "cancelled";
  const tokens = tokenText(message.usage);

  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        <Group gap="xs">
          <Badge variant="light" color="gray" tt="none">
            {modelLabel(models, message.model)}
          </Badge>
          {waiting && (
            <Text size="xs" c="dimmed">
              Waiting to start…
            </Text>
          )}
        </Group>

        {message.reasoning !== "" && <Thinking text={message.reasoning} active={active} />}

        {message.content !== "" ? (
          <MarkdownText>{message.content}</MarkdownText>
        ) : (
          active && <Loader size="xs" type="dots" />
        )}

        {message.history_dropped > 0 && (
          <Text size="xs" c="dimmed">
            The {message.history_dropped} oldest earlier messages were left out, because the chat is
            longer than this model accepts.
          </Text>
        )}

        {message.finish_reason === "length" && (
          <Alert color="yellow" variant="light" p="xs">
            The answer was cut off because the model reached its token limit.
          </Alert>
        )}

        {job?.status === "failed" && job.error && (
          <Alert color="red" variant="light" p="xs" title="This reply failed">
            {job.error}
            {message.content !== "" && " The text above is what was written before it failed."}
          </Alert>
        )}
        {job?.status === "cancelled" && (
          <Alert color="gray" variant="light" p="xs">
            This reply was cancelled.
          </Alert>
        )}

        <Group gap="xs">
          {job?.can_cancel && (
            <Button
              size="compact-xs"
              variant="subtle"
              color="red"
              loading={cancel.isPending}
              onClick={() => cancel.mutate(job.id, { onSuccess: onCancelled })}
            >
              Cancel
            </Button>
          )}
          {failed && isLast && (
            <Button
              size="compact-xs"
              variant="light"
              loading={retrying}
              onClick={() => onRetry(message.id)}
            >
              Try again
            </Button>
          )}
          {tokens && (
            <Text size="xs" c="dimmed">
              {tokens}
            </Text>
          )}
        </Group>
        {cancel.isError && (
          <Text size="xs" c="red">
            {describeError(cancel.error)}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

export function ChatMessageView(props: ChatMessageViewProps) {
  return props.message.role === "user" ? (
    <UserMessage message={props.message} />
  ) : (
    <AssistantMessage {...props} />
  );
}
