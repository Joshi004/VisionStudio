import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import type { components } from "./schema";

export type MusicCatalog = components["schemas"]["MusicCatalogOut"];
export type MusicModelInfo = components["schemas"]["MusicModelOut"];
export type MusicFieldSpec = components["schemas"]["FieldSpecOut"];
export type MusicKindInfo = components["schemas"]["MusicKindOut"];
export type MusicKind = MusicKindInfo["id"];
export type MusicModel = MusicModelInfo["id"];
export type MusicBrief = components["schemas"]["MusicBrief"];
export type MusicPromptDraftCreate = components["schemas"]["MusicPromptDraftCreate"];
export type LabMusicRun = components["schemas"]["LabMusicRunOut"];
export type LabMusicRunCreate = components["schemas"]["LabMusicRunCreate"];
export type MusicVerdict = NonNullable<LabMusicRun["verdict"]>;

const PAGE_SIZE = 20;

/** Every Music lab query starts with this key. */
export const MUSIC_LAB_KEY = ["lab", "music"] as const;
const runsKey = [...MUSIC_LAB_KEY, "runs"] as const;

async function fetchCatalog() {
  const { data, response } = await api.GET("/api/lab/music/models");
  if (!data) {
    throw new ApiError(`Could not load the music models (HTTP ${response.status}).`, response.status);
  }
  return data;
}

/** The kinds of sound, the models that make each, their fields and licence warnings. */
export function useMusicCatalog() {
  return useQuery({ queryKey: [...MUSIC_LAB_KEY, "models"], queryFn: fetchCatalog, staleTime: Infinity });
}

async function fetchRuns(beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/music/runs", {
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
 * of them is waiting or running, so a piece of audio appears by itself when it is done.
 */
export function useMusicLabRuns() {
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
 * Starts the job that writes the fields of one model from the brief (a paid call to the
 * language model). It answers with that job: follow it with `useJob`, and read `output.fields`
 * and `output.warnings` when it has succeeded.
 */
export function useCreateMusicPromptDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: MusicPromptDraftCreate) => {
      const { data, error, response } = await api.POST("/api/lab/music/prompt-drafts", { body });
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

/** Starts one run per chosen model and seed, and returns at once. Each is a paid GPU job. */
export function useCreateMusicLabRuns() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: LabMusicRunCreate) => {
      const { data, error, response } = await api.POST("/api/lab/music/runs", { body });
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

/** Records what a person decided after listening. Only the fields that are sent are changed. */
export function useUpdateMusicRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      runId: number;
      body: { verdict?: MusicVerdict | null; note?: string | null };
    }) => {
      const { data, error, response } = await api.PATCH("/api/lab/music/runs/{run_id}", {
        params: { path: { run_id: input.runId } },
        body: input.body,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The verdict was not saved (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: runsKey }),
  });
}
