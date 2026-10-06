import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

export type ProjectSummary = components["schemas"]["ProjectSummary"];
export type ProjectDetail = components["schemas"]["ProjectDetail"];
export type ProjectCreate = components["schemas"]["ProjectCreate"];
export type ProjectUpdate = components["schemas"]["ProjectUpdate"];

/** The backend's own limit. The server stays the judge; this only avoids a pointless upload. */
export const VOICEOVER_MAX_MB = 400;
/** What nginx accepts on /api/, before the backend sees the request. */
const NGINX_MAX_MB = 512;

const PROJECTS_KEY = ["projects"] as const;

async function fetchProjects() {
  const { data, response } = await api.GET("/api/projects");
  if (!data) {
    throw new ApiError(`Could not load the projects (HTTP ${response.status}).`, response.status);
  }
  return data;
}

export function useProjects() {
  return useQuery({ queryKey: PROJECTS_KEY, queryFn: fetchProjects });
}

async function fetchProject(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the project (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

export function isValidProjectId(projectId: number): boolean {
  return Number.isSafeInteger(projectId) && projectId > 0;
}

export function useProject(projectId: number) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId],
    queryFn: () => fetchProject(projectId),
    enabled: isValidProjectId(projectId),
    // A project that does not exist will not appear on a retry.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProjectCreate) => {
      const { data, error, response } = await api.POST("/api/projects", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not create the project (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROJECTS_KEY }),
  });
}

/** Settings, guidelines and the script are all saved this way: only changed fields are sent. */
export function useUpdateProject(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProjectUpdate) => {
      const { data, error, response } = await api.PATCH("/api/projects/{project_id}", {
        params: { path: { project_id: projectId } },
        body,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the project (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROJECTS_KEY }),
  });
}

async function uploadError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON, for example nginx's own error page.
  }
  if (response.status === 413 && body === null) {
    return new ApiError(
      `The file is larger than ${NGINX_MAX_MB} MB, the most the server accepts.`,
      413,
    );
  }
  return new ApiError(
    detailMessage(body, `The upload failed (HTTP ${response.status}).`),
    response.status,
  );
}

/**
 * Sends the file itself as the request body. The server decides what the file
 * is from its content, so the content type is always application/octet-stream.
 */
export function useUploadVoiceover(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      if (file.size > VOICEOVER_MAX_MB * 1024 * 1024) {
        throw new ApiError(`The file is larger than ${VOICEOVER_MAX_MB} MB.`, 413);
      }
      const response = await fetch(`/api/projects/${projectId}/voiceover`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as ProjectDetail;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROJECTS_KEY }),
  });
}
