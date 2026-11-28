import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { footageKey } from "./footage";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type FootageMarksState = components["schemas"]["FootageMarksState"];
export type FootageMark = components["schemas"]["FootageMarkOut"];
export type FootageMarkInput = components["schemas"]["FootageMarkIn"];
export type FootageMarkEdit = components["schemas"]["FootageMarkEditIn"];
export type FootageKind = FootageMark["kind_hint"];

/** The kinds a footage mark can have, in the order they are offered. */
export const FOOTAGE_KINDS: readonly { value: FootageKind; label: string }[] = [
  { value: "any", label: "Any" },
  { value: "video", label: "Video" },
  { value: "photo", label: "Photo" },
  { value: "page", label: "Web page" },
];

/**
 * Every footage marks query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the marks,
 * which are re-anchored on every read.
 */
export function footageMarksKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "footage-marks"] as const;
}

async function fetchFootageMarks(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/footage-marks", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the footage marks (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The footage marks as they stand in the story, and the newest job. It is loaded again every few
 * seconds while the job is waiting or running.
 */
export function useFootageMarks(projectId: number, enabled = true) {
  return useQuery({
    queryKey: footageMarksKey(projectId),
    queryFn: () => fetchFootageMarks(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/** Marks words of the saved story as footage. */
export function useMarkFootage(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: FootageMarkInput) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/footage-marks/marks",
        { params: { path: { project_id: projectId } }, body },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not mark the footage (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(footageMarksKey(projectId), data);
      // What the footage step waits for depends on the marks that count.
      void queryClient.invalidateQueries({ queryKey: footageKey(projectId) });
    },
  });
}

/** Changes a mark's note or kind, or keeps or drops a proposal of GLM. */
export function useEditFootageMark(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { markId: string; edit: FootageMarkEdit }) => {
      const { data, error, response } = await api.PATCH(
        "/api/projects/{project_id}/footage-marks/{mark_id}",
        {
          params: { path: { project_id: projectId, mark_id: input.markId } },
          body: input.edit,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the footage mark (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(footageMarksKey(projectId), data);
      // What the footage step waits for depends on the marks that count.
      void queryClient.invalidateQueries({ queryKey: footageKey(projectId) });
    },
  });
}

/** Removes one of the owner's marks. */
export function useRemoveFootageMark(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (markId: string) => {
      const { data, error, response } = await api.DELETE(
        "/api/projects/{project_id}/footage-marks/{mark_id}",
        { params: { path: { project_id: projectId, mark_id: markId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not remove the footage mark (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(footageMarksKey(projectId), data);
      // What the footage step waits for depends on the marks that count.
      void queryClient.invalidateQueries({ queryKey: footageKey(projectId) });
    },
  });
}

/** Starts the job that asks GLM for more footage marks (a paid call). */
export function useSuggestFootageMarks(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/footage-marks/suggest",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not ask GLM for footage (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: footageMarksKey(projectId) }),
        queryClient.invalidateQueries({ queryKey: footageKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
