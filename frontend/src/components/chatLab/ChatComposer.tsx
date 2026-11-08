import { useState, type KeyboardEvent } from "react";
import { Alert, Button, Group, Select, Stack, Text, Textarea } from "@mantine/core";

import type { ChatModel } from "../../api/chatLab";
import { describeError } from "../../api/errors";

type ChatComposerProps = {
  models: ChatModel[];
  model: string;
  onModelChange: (model: string) => void;
  /** True while the last reply is being written: a new message waits for it. */
  busy: boolean;
  /** Sends the message. The text is cleared when it resolves, and kept when it rejects. */
  onSend: (content: string) => Promise<void>;
};

/**
 * The box at the bottom: the model for the next message and the message itself. Enter sends,
 * Shift+Enter starts a new line.
 */
export function ChatComposer({ models, model, onModelChange, busy, onSend }: ChatComposerProps) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const selected = models.find((item) => item.id === model);
  const canSend = text.trim() !== "" && !busy && !sending;

  async function send() {
    if (!canSend) {
      return;
    }
    setSending(true);
    setError(null);
    try {
      await onSend(text.trim());
      setText("");
    } catch (caught) {
      setError(caught);
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter while an input method is composing a character (Japanese, Chinese) confirms it.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  return (
    <Stack gap="xs">
      {error != null && (
        <Alert color="red" variant="light" p="xs">
          {describeError(error)}
        </Alert>
      )}
      <Textarea
        value={text}
        onChange={(event) => setText(event.currentTarget.value)}
        onKeyDown={onKeyDown}
        placeholder={busy ? "The reply is being written…" : "Write a message (Shift+Enter for a new line)"}
        autosize
        minRows={2}
        maxRows={10}
        aria-label="Message"
      />
      <Group justify="space-between" align="flex-end" wrap="nowrap">
        <Stack gap={2}>
          <Select
            size="xs"
            w={320}
            aria-label="Model for the next message"
            data={models.map((item) => ({ value: item.id, label: item.label }))}
            value={model}
            onChange={(value) => value && onModelChange(value)}
            allowDeselect={false}
            checkIconPosition="right"
          />
          {selected?.note && (
            <Text size="xs" c="dimmed" maw={420}>
              {selected.note}
            </Text>
          )}
        </Stack>
        <Button onClick={() => void send()} disabled={!canSend} loading={sending}>
          Send
        </Button>
      </Group>
    </Stack>
  );
}
