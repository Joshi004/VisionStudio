import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import type { components } from "./schema";
import { VIDEO_LAB_KEY } from "./videoLab";
import { VOICE_LAB_KEY } from "./voiceLab";

export type TalkTake = components["schemas"]["TalkTakeOut"];
export type TalkTakeCreate = components["schemas"]["TalkTakeCreate"];
export type TalkPromptDraftCreate = components["schemas"]["TalkPromptDraftCreate"];
export type TalkStep = NonNullable<TalkTake["next_step"]>;

const PAGE_SIZE = 20;

/** Every Talking character lab query starts with this key. */
export const TALK_LAB_KEY = ["lab", "talk"] as const;
const takesKey = [...TALK_LAB_KEY, "takes"] as const;

async function fetchTakes(beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/talk/takes", {
    params: { query: { before_id: beforeId, limit: PAGE_SIZE } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the takes (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The takes, newest first, a page at a time. They are loaded again every few seconds while any
 * of them has a step that is waiting or running, so the speech and the clip appear by
 * themselves when they are done.
 */
export function useTalkTakes() {
  return useInfiniteQuery({
    queryKey: takesKey,
    queryFn: ({ pageParam }) => fetchTakes(pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE_SIZE ? last[last.length - 1].id : undefined),
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.some((take) => take.running_step !== null))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/**
 * A take makes a speech and a clip: they also appear in the Voice lab and the Video lab, and a
 * step that starts by itself (the speech after the prompts, the clip after the speech) creates
 * a run there that those lists have not seen yet.
 */
export function invalidateAfterTakeChange(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: takesKey }),
    queryClient.invalidateQueries({ queryKey: VOICE_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VIDEO_LAB_KEY }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/**
 * Saves a take and starts its first step, and returns at once. Each step is a paid call: the
 * prompts a call to the language model, the speech a GPU job of one to three minutes, the clip
 * one of 5 to 10 minutes.
 */
export function useCreateTalkTake() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: TalkTakeCreate) => {
      const { data, error, response } = await api.POST("/api/lab/talk/takes", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The take was not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterTakeChange(queryClient),
  });
}

/** Starts the next step of a take (one step). */
export function useContinueTalkTake() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (takeId: number) => {
      const { data, error, response } = await api.POST("/api/lab/talk/takes/{take_id}/continue", {
        params: { path: { take_id: takeId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The step was not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterTakeChange(queryClient),
  });
}

/**
 * Starts the job that writes the voice instruction and the video prompt from a line of
 * dialogue (a paid call to the language model). It answers with that job: follow it with
 * `useJob`, and read `output.voice_instruction` and `output.video_prompt` when it has succeeded.
 */
export function useCreateTalkPromptDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: TalkPromptDraftCreate) => {
      const { data, error, response } = await api.POST("/api/lab/talk/prompt-drafts", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The prompts were not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}
