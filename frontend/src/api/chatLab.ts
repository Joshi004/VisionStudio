import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { CHAT_POLL_MS, isJobActive } from "./polling";
import type { components } from "./schema";

export type ChatModel = components["schemas"]["ChatModelOut"];
export type ChatSummary = components["schemas"]["ChatSummaryOut"];
export type Chat = components["schemas"]["ChatOut"];
export type ChatMessage = components["schemas"]["ChatMessageOut"];

/** Every Text lab query starts with this key. */
export const CHAT_LAB_KEY = ["lab", "chat"] as const;
const modelsKey = [...CHAT_LAB_KEY, "models"] as const;
const listKey = [...CHAT_LAB_KEY, "list"] as const;
const chatKey = (chatId: number | null) => [...CHAT_LAB_KEY, "chat", chatId] as const;

/** A reply is being written while its job is waiting or running. */
export function isReplyActive(message: ChatMessage | undefined): boolean {
  return message?.role === "assistant" && isJobActive(message.job);
}

/** The reply that is being written now, or null. Only the last message can be one. */
export function activeReply(chat: Chat | undefined): ChatMessage | null {
  const last = chat?.messages[chat.messages.length - 1];
  return last !== undefined && isReplyActive(last) ? last : null;
}

/** The models the chat can use. The list is fixed in the backend, so it is loaded once. */
export function useChatModels() {
  return useQuery({
    queryKey: modelsKey,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/lab/chat/models");
      if (!data) {
        throw new ApiError(`Could not load the models (HTTP ${response.status}).`, response.status);
      }
      return data;
    },
    staleTime: Infinity,
  });
}

/** The chats, the most recently used first. */
export function useChats() {
  return useQuery({
    queryKey: listKey,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/lab/chats");
      if (!data) {
        throw new ApiError(`Could not load the chats (HTTP ${response.status}).`, response.status);
      }
      return data;
    },
  });
}

/**
 * One chat with all its messages. Nothing is loaded while `chatId` is null. While the last reply
 * is being written the chat is loaded again every second, so the answer appears as it grows.
 */
export function useChat(chatId: number | null) {
  return useQuery({
    queryKey: chatKey(chatId),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/chats/{chat_id}", {
        params: { path: { chat_id: chatId as number } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not load the chat (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    enabled: chatId !== null,
    refetchInterval: (query) => (activeReply(query.state.data) ? CHAT_POLL_MS : false),
  });
}

export function useCreateChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (model: string | null) => {
      const { data, error, response } = await api.POST("/api/lab/chats", { body: { model } });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The chat was not created (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey }),
  });
}

/**
 * Sends a message and starts the reply. The answer of the server is the chat with the new
 * messages, so it is shown at once, before the next poll.
 */
export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { chatId: number; content: string; model: string }) => {
      const { data, error, response } = await api.POST("/api/lab/chats/{chat_id}/messages", {
        params: { path: { chat_id: input.chatId } },
        body: { content: input.content, model: input.model },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The message was not sent (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (chat) => {
      queryClient.setQueryData(chatKey(chat.id), chat);
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: listKey }),
        invalidateAfterJobAction(queryClient),
      ]);
    },
  });
}

/** Asks again for the last reply, after it failed or was cancelled. */
export function useRetryReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { chatId: number; messageId: number; model: string | null }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/chats/{chat_id}/messages/{message_id}/retry",
        {
          params: { path: { chat_id: input.chatId, message_id: input.messageId } },
          body: { model: input.model },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The reply was not started again (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (chat) => {
      queryClient.setQueryData(chatKey(chat.id), chat);
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: listKey }),
        invalidateAfterJobAction(queryClient),
      ]);
    },
  });
}

export function useRenameChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { chatId: number; title: string }) => {
      const { data, error, response } = await api.PATCH("/api/lab/chats/{chat_id}", {
        params: { path: { chat_id: input.chatId } },
        body: { title: input.title },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The chat was not renamed (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (_chat, input) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: listKey }),
        queryClient.invalidateQueries({ queryKey: chatKey(input.chatId) }),
      ]),
  });
}

export function useDeleteChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (chatId: number) => {
      const { error, response } = await api.DELETE("/api/lab/chats/{chat_id}", {
        params: { path: { chat_id: chatId } },
      });
      if (!response.ok) {
        throw new ApiError(
          detailMessage(error, `The chat was not deleted (HTTP ${response.status}).`),
          response.status,
        );
      }
    },
    onSuccess: (_data, chatId) => {
      queryClient.removeQueries({ queryKey: chatKey(chatId) });
      return queryClient.invalidateQueries({ queryKey: listKey });
    },
  });
}

/** Loads the chat again, for a page that changed a job the chat shows (a cancelled reply). */
export function useRefreshChat(chatId: number | null) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: chatKey(chatId) });
}
