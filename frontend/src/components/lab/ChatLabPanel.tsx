import { useState } from "react";
import { Alert, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import {
  activeReply,
  useChat,
  useChatModels,
  useChats,
  useCreateChat,
  useRefreshChat,
  useRetryReply,
  useSendMessage,
} from "../../api/chatLab";
import { describeError } from "../../api/errors";
import { ChatComposer } from "../chatLab/ChatComposer";
import { ChatList } from "../chatLab/ChatList";
import { ChatThread } from "../chatLab/ChatThread";

/**
 * The Text lab: a chat with a language model chosen for every message. The chats are saved on
 * the server, which sends the whole conversation to the model each time, so the page only sends
 * the new message. An answer is saved while it is written and appears as it grows.
 */
export function ChatLabPanel() {
  const models = useChatModels();
  const chats = useChats();
  const createChat = useCreateChat();
  const send = useSendMessage();
  const retry = useRetryReply();

  // Null: a new chat that is created when its first message is sent.
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // The model of the next message. It follows the chat that is opened.
  const [model, setModel] = useState<string | null>(null);
  const chat = useChat(selectedId);
  const refreshChat = useRefreshChat(selectedId);

  if (models.isPending || chats.isPending) {
    return <Loader size="sm" />;
  }
  if (models.isError || chats.isError) {
    return (
      <Alert color="red" variant="light">
        {describeError(models.error ?? chats.error)}
      </Alert>
    );
  }

  const modelList = models.data.models;
  const currentModel = model ?? models.data.default_model;
  const busy = activeReply(chat.data) !== null;

  function select(chatId: number) {
    setSelectedId(chatId);
    const summary = chats.data?.find((item) => item.id === chatId);
    if (summary && modelList.some((item) => item.id === summary.model)) {
      setModel(summary.model);
    }
  }

  async function sendMessage(content: string) {
    let chatId = selectedId;
    if (chatId === null) {
      const created = await createChat.mutateAsync(currentModel);
      chatId = created.id;
      setSelectedId(chatId);
    }
    await send.mutateAsync({ chatId, content, model: currentModel });
  }

  return (
    <Stack gap="md" maw={1300}>
      <Text c="dimmed">
        Chat with a model. Pick the model for each message; the whole conversation is sent to it
        every time. Answers appear as they are written.
      </Text>
      <Group align="flex-start" wrap="nowrap" gap="md">
        <Paper withBorder p="sm" radius="md" w={260} style={{ flexShrink: 0 }}>
          <ChatList
            chats={chats.data}
            selectedId={selectedId}
            onSelect={select}
            onNew={() => setSelectedId(null)}
            onDeleted={(chatId) => {
              if (chatId === selectedId) {
                setSelectedId(null);
              }
            }}
          />
        </Paper>
        <Paper withBorder p="md" radius="md" style={{ flex: 1, minWidth: 0 }}>
          <Stack gap="md">
            {chat.isError && selectedId !== null && (
              <Alert color="red" variant="light">
                {describeError(chat.error)}
              </Alert>
            )}
            <ChatThread
              chat={selectedId === null ? undefined : chat.data}
              models={modelList}
              retrying={retry.isPending}
              onRetry={(messageId) =>
                selectedId !== null && retry.mutate({ chatId: selectedId, messageId, model: null })
              }
              onCancelled={() => void refreshChat()}
            />
            {retry.isError && (
              <Alert color="red" variant="light" p="xs">
                {describeError(retry.error)}
              </Alert>
            )}
            <ChatComposer
              models={modelList}
              model={currentModel}
              onModelChange={setModel}
              busy={busy}
              onSend={sendMessage}
            />
          </Stack>
        </Paper>
      </Group>
    </Stack>
  );
}
