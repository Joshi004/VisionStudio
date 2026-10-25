import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { uploadError } from "./projects";
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
export type MusicEditOperation = MusicCatalog["operations"][number];
export type MusicEditModel = MusicEditOperation["models"][number];
export type MusicEditCreate = components["schemas"]["MusicEditCreate"];
export type MusicSource = components["schemas"]["MusicSourceOut"];
export type MusicSourceJoin = components["schemas"]["MusicSourceJoin"];
export type RunSource = components["schemas"]["RunSourceOut"];
export type AudioMeasurement = components["schemas"]["AudioMeasurementOut"];
export type OutsideWindow = components["schemas"]["OutsideWindowOut"];
export type MusicTrialCase = components["schemas"]["TrialCaseOut"];
export type MusicTrialSource = components["schemas"]["TrialSourceOut"];
export type TrialAnswer = NonNullable<MusicTrialCase["answer"]>;

/** The backend's own limit. The server stays the judge; this only avoids a pointless upload. */
export const SOURCE_UPLOAD_MAX_MB = 200;

const PAGE_SIZE = 20;

/** Every Music lab query starts with this key. */
export const MUSIC_LAB_KEY = ["lab", "music"] as const;
const runsKey = [...MUSIC_LAB_KEY, "runs"] as const;
const trialsKey = [...MUSIC_LAB_KEY, "trials"] as const;

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
    // The same run is shown in the trial cases too.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: runsKey }),
        queryClient.invalidateQueries({ queryKey: trialsKey }),
      ]),
  });
}

const sourcesKey = [...MUSIC_LAB_KEY, "sources"] as const;

/** The recordings and joins that can be edited, newest first. */
export function useMusicSources() {
  return useQuery({
    queryKey: sourcesKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/music/sources");
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not load the sources (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  });
}

/** Stores a recording to edit. The recording is the request body; its name goes in the query. */
export function useUploadMusicSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { file: File; name: string }) => {
      if (input.file.size > SOURCE_UPLOAD_MAX_MB * 1024 * 1024) {
        throw new ApiError(`The recording is larger than ${SOURCE_UPLOAD_MAX_MB} MB.`, 413);
      }
      const query = new URLSearchParams({ name: input.name });
      const response = await fetch(`/api/lab/music/sources/upload?${query.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: input.file,
      });
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as MusicSource;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sourcesKey }),
  });
}

/** Joins two finished runs into one recording to edit. */
export function useJoinMusicSources() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: MusicSourceJoin) => {
      const { data, error, response } = await api.POST("/api/lab/music/sources/join", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The runs were not joined (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sourcesKey }),
  });
}

/** Starts one edit job per variant. Each is a paid GPU job, like a run. */
export function useCreateMusicEdits() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: MusicEditCreate) => {
      const { data, error, response } = await api.POST("/api/lab/music/edits", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The edit was not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: runsKey }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * What was measured in a run's audio. Fetched once the audio exists and kept: the audio of a
 * run never changes. A run whose audio cannot be measured answers with an error, which the
 * card shows as "unavailable".
 */
export function useRunMeasurements(runId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...MUSIC_LAB_KEY, "measurements", runId],
    enabled,
    staleTime: Infinity,
    retry: false,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/music/runs/{run_id}/measurements", {
        params: { path: { run_id: runId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not measure the run (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  });
}

/**
 * How much a repaint or an inpaint changed the sound outside its window. Computed by the server
 * when asked and kept here: a run's audio never changes.
 */
export function useRunOutsideWindow(runId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...MUSIC_LAB_KEY, "outside-window", runId],
    enabled,
    staleTime: Infinity,
    retry: false,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/music/runs/{run_id}/outside-window", {
        params: { path: { run_id: runId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not compare the run (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  });
}

/**
 * The cases of the round-2 trials with their guide text, source audio, runs and answers. Loaded
 * again every few seconds while any run is waiting or running.
 */
export function useMusicTrials() {
  return useQuery({
    queryKey: trialsKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/music/trials");
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not load the trial cases (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    refetchInterval: (query) =>
      query.state.data?.some((trial) => trial.runs.some((run) => isJobActive(run.job)))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** Records the answer and/or the note of a trial case. Only the fields that are sent change. */
export function useUpdateMusicTrial() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      caseId: string;
      body: { answer?: TrialAnswer | null; answer_note?: string | null };
    }) => {
      const { data, error, response } = await api.PATCH("/api/lab/music/trials/{case_id}", {
        params: { path: { case_id: input.caseId } },
        body: input.body,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The answer was not saved (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: trialsKey }),
  });
}
