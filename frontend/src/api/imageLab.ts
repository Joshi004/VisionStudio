import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { isValidProjectId, uploadError } from "./projects";
import type { components } from "./schema";

export type LabRun = components["schemas"]["LabRunOut"];
export type LabImage = components["schemas"]["LabImageOut"];
export type LabReferenceIn = components["schemas"]["LabReferenceIn"];
export type LabRunRequest = components["schemas"]["LabRunRequest"];
export type LabMode = LabRun["mode"];
export type ProjectFrame = components["schemas"]["ProjectFrameOut"];

/** The backend's own limit. The server stays the judge; this only avoids a pointless upload. */
export const LAB_UPLOAD_MAX_MB = 40;
/** What Bitdeer's price list says for one generated image. Shown as an estimate only. */
export const PRICE_PER_IMAGE_USD = 0.035;
export const MAX_REFERENCES = 14;
const PAGE_SIZE = 20;

/** Every Image lab query starts with this key. */
export const LAB_KEY = ["lab", "images"] as const;
const runsKey = [...LAB_KEY, "runs"] as const;
const libraryKey = [...LAB_KEY, "library"] as const;

async function fetchRuns(beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/images/runs", {
    params: { query: { before_id: beforeId, limit: PAGE_SIZE } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the history (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The history, newest first, a page at a time. Reads the database only. */
export function useLabRuns() {
  return useInfiniteQuery({
    queryKey: runsKey,
    queryFn: ({ pageParam }) => fetchRuns(pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
  });
}

/** One run with its request and its answer, for the drawer. */
export function useLabRun(runId: number | null) {
  return useQuery({
    queryKey: [...LAB_KEY, "run", runId],
    enabled: runId !== null,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/images/runs/{run_id}", {
        params: { path: { run_id: runId ?? 0 } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not load the run (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  });
}

/** The lab's own images: uploads and results, newest first. */
export function useLabLibrary(enabled: boolean) {
  return useQuery({
    queryKey: libraryKey,
    enabled,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/lab/images/library");
      if (!data) {
        throw new ApiError(
          `Could not load the images (HTTP ${response.status}).`,
          response.status,
        );
      }
      return data.images;
    },
  });
}

/** A project's frames, newest first. Idle until a project is chosen. */
export function useProjectFrames(projectId: number | null) {
  return useQuery({
    queryKey: [...LAB_KEY, "project-frames", projectId],
    enabled: projectId !== null && isValidProjectId(projectId),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/images/project-frames", {
        params: { query: { project_id: projectId ?? 0 } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not load the frames (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data.frames;
    },
  });
}

/**
 * Makes one call to the image API (a paid call, 25 to 40 s) and answers with the saved run.
 * A call that failed is a saved run too, so it comes back as data, not as an error: only a
 * form the server refuses (422) is an error here.
 */
export function useRunLab() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: LabRunRequest) => {
      const { data, error, response } = await api.POST("/api/lab/images/runs", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The run was not made (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: runsKey });
      void queryClient.invalidateQueries({ queryKey: libraryKey });
    },
  });
}

/** Sends the image itself as the request body, as a scene's frame is sent. */
export function useLabUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      if (file.size > LAB_UPLOAD_MAX_MB * 1024 * 1024) {
        throw new ApiError(`The file is larger than ${LAB_UPLOAD_MAX_MB} MB.`, 413);
      }
      const response = await fetch("/api/lab/images/uploads", {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as LabImage;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: libraryKey }),
  });
}
