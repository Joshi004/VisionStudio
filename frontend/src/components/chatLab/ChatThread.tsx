import { useEffect, useRef } from "react";
import { Center, ScrollArea, Stack, Text } from "@mantine/core";

import type { Chat, ChatModel } from "../../api/chatLab";
import { ChatMessageView } from "./ChatMessageView";

/** How close to the bottom (in pixels) counts as "following the answer". */
const FOLLOW_DISTANCE_PX = 120;

type ChatThreadProps = {
  /** Null for a new chat that has no message yet. */
  chat: Chat | undefined;
  models: ChatModel[];
  retrying: boolean;
  onRetry: (messageId: number) => void;
  onCancelled: () => void;
};

/**
 * The messages of a chat. While an answer grows, the view follows its end, unless the reader
 * scrolled up to read something: then it stays where it is.
 */
export function ChatThread({ chat, models, retrying, onRetry, onCancelled }: ChatThreadProps) {
  const viewport = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  const messages = chat?.messages ?? [];
  const last = messages[messages.length - 1];
  const growth = `${chat?.id ?? 0}:${messages.length}:${last?.content.length ?? 0}:${last?.reasoning.length ?? 0}`;

  useEffect(() => {
    const element = viewport.current;
    if (element && following.current) {
      element.scrollTo({ top: element.scrollHeight });
    }
  }, [growth]);

  // Opening another chat starts at its end.
  useEffect(() => {
    following.current = true;
  }, [chat?.id]);

  return (
    <ScrollArea
      h="60vh"
      viewportRef={viewport}
      onScrollPositionChange={({ y }) => {
        const element = viewport.current;
        if (element) {
          following.current =
            element.scrollHeight - element.clientHeight - y < FOLLOW_DISTANCE_PX;
        }
      }}
    >
      {messages.length === 0 ? (
        <Center h="55vh">
          <Text c="dimmed">Pick a model and write a message to start.</Text>
        </Center>
      ) : (
        <Stack gap="md" pr="sm" pb="sm">
          {messages.map((message, index) => (
            <ChatMessageView
              key={message.id}
              message={message}
              isLast={index === messages.length - 1}
              models={models}
              retrying={retrying}
              onRetry={onRetry}
              onCancelled={onCancelled}
            />
          ))}
        </Stack>
      )}
    </ScrollArea>
  );
}
