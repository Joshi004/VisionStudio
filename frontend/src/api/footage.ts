import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { pipelineBoardKey } from "./pipelineBoard";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type FootageState = components["schemas"]["FootageStateOut"];
export type FootageRound = components["schemas"]["FootageRoundOut"];
export type FootageMarkState = components["schemas"]["FootageMarkStateOut"];

/**
 * The footage research query of a project. It sits under the project's own key, so whatever
 * refreshes the project refreshes it, and changing a mark or a file refreshes it too
 * (`api/footageMarks.ts`, `api/footageFiles.ts`).
 */
export function footageKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "footage"] as const;
}

async function fetchFootage(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/footage", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the footage (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** Where the project's footage research stands. Loaded again every few seconds while the brief
 * is written. */
export function useFootage(projectId: number, enabled = true) {
  return useQuery({
    queryKey: footageKey(projectId),
    queryFn: () => fetchFootage(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/** Starts the job that writes the next round's brief into the files folder. */
export function useWriteFootageBrief(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/footage/brief",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not write the brief (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: footageKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** A choice of "no footage here" changes whether the `footage` step is done, so the board is
 * refreshed too. */
function useAfterChoice(projectId: number) {
  const queryClient = useQueryClient();
  return (data: FootageState) => {
    queryClient.setQueryData(footageKey(projectId), data);
    return queryClient.invalidateQueries({ queryKey: pipelineBoardKey(projectId) });
  };
}

/** Sets "no footage here" on every mark that is waiting, so the full render can go on. */
export function useContinueWithoutFootage(projectId: number) {
  const afterChoice = useAfterChoice(projectId);
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/footage/continue-without",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not continue without footage (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterChoice,
  });
}

/** Takes "no footage here" off one mark, so it waits for research again. */
export function useUndoNoFootage(projectId: number) {
  const afterChoice = useAfterChoice(projectId);
  return useMutation({
    mutationFn: async (markId: string) => {
      const { data, error, response } = await api.DELETE(
        "/api/projects/{project_id}/footage/marks/{mark_id}/no-footage",
        { params: { path: { project_id: projectId, mark_id: markId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not undo the choice (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterChoice,
  });
}
