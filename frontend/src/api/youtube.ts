import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

export type YouTubeConfig = components["schemas"]["YouTubeConfig"];
export type YouTubeChannel = components["schemas"]["YouTubeChannelOut"];

const CONFIG_KEY = ["youtube", "config"] as const;
const CHANNELS_KEY = ["youtube", "channels"] as const;

export function useYouTubeConfig() {
  return useQuery({
    queryKey: CONFIG_KEY,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/youtube/config");
      if (!data) {
        throw new ApiError(
          `Could not check the YouTube setup (HTTP ${response.status}).`,
          response.status,
        );
      }
      return data;
    },
  });
}

export function useYouTubeChannels() {
  return useQuery({
    queryKey: CHANNELS_KEY,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/youtube/channels");
      if (!data) {
        throw new ApiError(
          `Could not load the YouTube channels (HTTP ${response.status}).`,
          response.status,
        );
      }
      return data;
    },
  });
}

/** Asks for Google's sign-in address, then sends the browser there. It comes back to Settings. */
export function useStartYouTubeSignIn() {
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.GET("/api/youtube/oauth/start");
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the sign-in (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data.url;
    },
    onSuccess: (url) => {
      window.location.assign(url);
    },
  });
}

/** Uses the channel's token once. A refused token turns the channel to "needs reconnect". */
export function useCheckYouTubeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (channelRowId: number) => {
      const { data, error, response } = await api.POST(
        "/api/youtube/channels/{channel_row_id}/check",
        { params: { path: { channel_row_id: channelRowId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not check the channel (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: CHANNELS_KEY }),
  });
}

export function useDisconnectYouTubeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (channelRowId: number) => {
      const { data, error, response } = await api.DELETE(
        "/api/youtube/channels/{channel_row_id}",
        { params: { path: { channel_row_id: channelRowId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not disconnect the channel (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_KEY }),
  });
}
