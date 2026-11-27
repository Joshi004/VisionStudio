import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId, uploadError } from "./projects";
import type { components } from "./schema";

export type FootageFilesState = components["schemas"]["FootageFilesState"];
export type FootageFile = components["schemas"]["FootageFileOut"];
export type FootageFileKind = FootageFile["kind"];

/** The limits the server enforces (the server stays the judge; these only save a long upload). */
export const FOOTAGE_IMAGE_MAX_MB = 20;
export const FOOTAGE_VIDEO_MAX_MB = 500;
/** The part of a video that is shown moves in steps of this many seconds. */
export const FOOTAGE_USE_STEP_S = 0.5;
export const FOOTAGE_USE_MIN_S = 2;
export const FOOTAGE_USE_MAX_S = 30;
export const FOOTAGE_CREDIT_MAX_CHARS = 120;
/** What the file picker offers. */
export const FOOTAGE_FILE_ACCEPT =
  "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/x-matroska,video/webm,.mp4,.mov,.m4v,.mkv,.webm";

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp"];
const VIDEO_EXTENSIONS = ["mp4", "mov", "m4v", "mkv", "webm"];

/** Whether a file is a photo or a video, from its type or (when the browser gives none) its name. */
export function footageKindOf(file: File): FootageFileKind | null {
  if (file.type.startsWith("image/")) {
    return "image";
  }
  if (file.type.startsWith("video/")) {
    return "video";
  }
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_EXTENSIONS.includes(extension)) {
    return "image";
  }
  return VIDEO_EXTENSIONS.includes(extension) ? "video" : null;
}

/** Every footage files query of a project starts with this key (and the project's own key). */
export function footageFilesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "footage-files"] as const;
}

async function fetchFootageFiles(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/footage-files", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the footage files (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The owner's files on each mark. Loaded again every few seconds while a video is prepared. */
export function useFootageFiles(projectId: number, enabled = true) {
  return useQuery({
    queryKey: footageFilesKey(projectId),
    queryFn: () => fetchFootageFiles(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (query) => (query.state.data?.preparing ? ACTIVE_POLL_MS : false),
  });
}

/** Adds a photo or a video to a footage mark. The file is accepted at once. */
export function useUploadFootageFile(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { markId: string; file: File; credit: string }) => {
      const kind = footageKindOf(input.file);
      if (kind === null) {
        throw new ApiError(
          "Choose a PNG, JPEG or WebP photo, or an MP4, MOV, MKV or WebM video.",
          422,
        );
      }
      const maxMb = kind === "image" ? FOOTAGE_IMAGE_MAX_MB : FOOTAGE_VIDEO_MAX_MB;
      if (input.file.size > maxMb * 1024 * 1024) {
        throw new ApiError(`The file is larger than ${maxMb} MB.`, 413);
      }
      const query = new URLSearchParams({ kind });
      const credit = input.credit.trim();
      if (credit !== "") {
        query.set("credit", credit);
      }
      const response = await fetch(
        `/api/projects/${projectId}/footage-marks/${encodeURIComponent(input.markId)}/files?${query.toString()}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: input.file,
        },
      );
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as components["schemas"]["FootageFileStored"];
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: footageFilesKey(projectId) }),
  });
}

/** Takes a file off its mark. */
export function useRemoveFootageFile(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (itemKey: string) => {
      const { data, error, response } = await api.DELETE(
        "/api/projects/{project_id}/footage-files/{item_key}",
        { params: { path: { project_id: projectId, item_key: itemKey } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not remove the file (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(footageFilesKey(projectId), data);
    },
  });
}

/** Puts the files shown on a mark in a new order. */
export function useReorderFootageFiles(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { markId: string; shown: string[] }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/footage-marks/{mark_id}/order",
        {
          params: { path: { project_id: projectId, mark_id: input.markId } },
          body: { shown: input.shown },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the order (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(footageFilesKey(projectId), data);
    },
  });
}

/** Moves where a video starts and ends. */
export function useSetFootageUse(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { itemKey: string; startS: number; endS: number }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/footage-files/{item_key}/use",
        {
          params: { path: { project_id: projectId, item_key: input.itemKey } },
          body: { start_s: input.startS, end_s: input.endS },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not move the start and end (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(footageFilesKey(projectId), data);
    },
  });
}
