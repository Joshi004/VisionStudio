import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import type { components } from "./schema";

export type LabVideoRun = components["schemas"]["LabVideoRunOut"];
export type LabVideoRunCreate = components["schemas"]["LabVideoRunCreate"];
export type PromptDraftCreate = components["schemas"]["PromptDraftCreate"];

const PAGE_SIZE = 20;

/** Every Video lab query starts with this key. */
export const VIDEO_LAB_KEY = ["lab", "videos"] as const;
const runsKey = [...VIDEO_LAB_KEY, "runs"] as const;

async function fetchRuns(beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/videos/runs", {
    params: { query: { before_id: beforeId, limit: PAGE_SIZE } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the runs (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The runs, newest first, a page at a time. They are loaded again every few seconds while any
 * of them is waiting or running, so a clip appears by itself when it is done.
 */
export function useLabVideoRuns() {
  return useInfiniteQuery({
    queryKey: runsKey,
    queryFn: ({ pageParam }) => fetchRuns(pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE_SIZE ? last[last.length - 1].id : undefined),
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.some((run) => isJobActive(run.job)))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/**
 * Starts one run per chosen model and returns at once. Each run is a paid GPU job of 5 to 10
 * minutes: the page follows them by itself.
 */
export function useCreateLabVideoRuns() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: LabVideoRunCreate) => {
      const { data, error, response } = await api.POST("/api/lab/videos/runs", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The runs were not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // New jobs: the runs, the job lists and the banner's waiting count all change.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: runsKey }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * Starts the job that writes a multi-shot prompt from an idea (a paid call to the language
 * model). It answers with that job: follow it with `useJob`, and read `output.prompt` when it
 * has succeeded.
 */
export function useCreatePromptDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: PromptDraftCreate) => {
      const { data, error, response } = await api.POST("/api/lab/videos/prompt-drafts", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The prompt was not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}
