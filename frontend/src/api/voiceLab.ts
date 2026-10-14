import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId, PROJECTS_KEY, uploadError } from "./projects";
import type { components } from "./schema";

export type VoiceLabRun = components["schemas"]["LabVoiceRunOut"];
export type VoiceLabRunCreate = components["schemas"]["LabVoiceRunCreate"];
export type Voice = components["schemas"]["VoiceOut"];
export type VoiceUpdate = components["schemas"]["VoiceUpdate"];
export type VoiceoverGeneration = components["schemas"]["VoiceoverGenerationOut"];

/** The backend's own limit. The server stays the judge; this only avoids a pointless upload. */
export const VOICE_UPLOAD_MAX_MB = 50;

const PAGE_SIZE = 20;

/** Every Voice lab query starts with this key. */
export const VOICE_LAB_KEY = ["lab", "voices"] as const;
const runsKey = [...VOICE_LAB_KEY, "runs"] as const;
/** The saved voices. Projects use them too, so it is a key of its own. */
export const VOICES_KEY = ["voices"] as const;

async function fetchRuns(beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/voices/runs", {
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
 * of them is waiting or running, so a speech appears by itself when it is done.
 */
export function useVoiceLabRuns() {
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

async function fetchRun(runId: number) {
  const { data, error, response } = await api.GET("/api/lab/voices/runs/{run_id}", {
    params: { path: { run_id: runId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the speech (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * One run, for a page that follows a single speech (a character's voice audition). Nothing is
 * loaded while `runId` is null. It is loaded again every few seconds while the run is waiting
 * or running.
 */
export function useVoiceLabRun(runId: number | null) {
  return useQuery({
    queryKey: [...VOICE_LAB_KEY, "run", runId],
    queryFn: () => fetchRun(runId as number),
    enabled: runId !== null,
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/** Starts one run and returns at once. A run is a paid GPU job of one to three minutes. */
export function useCreateVoiceLabRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: VoiceLabRunCreate) => {
      const { data, error, response } = await api.POST("/api/lab/voices/runs", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The run was not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // A new job: the runs, the job lists and the banner's waiting count all change.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: runsKey }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

async function fetchVoices() {
  const { data, response } = await api.GET("/api/voices");
  if (!data) {
    throw new ApiError(`Could not load the voices (HTTP ${response.status}).`, response.status);
  }
  return data;
}

/** The saved voices, newest first. */
export function useVoices() {
  return useQuery({ queryKey: VOICES_KEY, queryFn: fetchVoices });
}

/**
 * Saves a recording as a voice. The recording is the request body, as a voiceover is sent;
 * its name and what it says go in the query.
 */
export function useUploadVoice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { file: File; name: string; transcript: string }) => {
      if (input.file.size > VOICE_UPLOAD_MAX_MB * 1024 * 1024) {
        throw new ApiError(`The recording is larger than ${VOICE_UPLOAD_MAX_MB} MB.`, 413);
      }
      const query = new URLSearchParams({ name: input.name, transcript: input.transcript });
      const response = await fetch(`/api/voices?${query.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: input.file,
      });
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as Voice;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: VOICES_KEY }),
  });
}

/** Saves the speech of a finished run as a voice. */
export function useSaveRunAsVoice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { runId: number; name: string; transcript: string }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/voices/runs/{run_id}/save-voice",
        {
          params: { path: { run_id: input.runId } },
          body: { name: input.name, transcript: input.transcript },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The voice was not saved (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: VOICES_KEY }),
  });
}

/** Changes a voice's name and/or transcript. */
export function useUpdateVoice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { voiceId: number; body: VoiceUpdate }) => {
      const { data, error, response } = await api.PATCH("/api/voices/{voice_id}", {
        params: { path: { voice_id: input.voiceId } },
        body: input.body,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The voice was not saved (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: VOICES_KEY }),
  });
}

// --- A project's voiceover, made from its script ---------------------------------------------

async function fetchGeneration(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/voiceover/generation",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the voiceover job (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest job that makes the project's voiceover from its script, and whether the
 * voiceover is up to date. It lives under the project's key, so saving the script refreshes
 * it, and it is loaded again every few seconds while the job is waiting or running.
 */
export function useVoiceoverGeneration(projectId: number) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, "voiceover-generation"],
    queryFn: () => fetchGeneration(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/** Starts making the voiceover and returns at once. The page follows the job by itself. */
export function useGenerateVoiceover(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/voiceover/generate",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the voiceover (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}
