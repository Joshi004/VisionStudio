import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";

export type MusicPlanState = components["schemas"]["MusicPlanState"];
export type MusicPlanOut = components["schemas"]["MusicPlanOut"];
export type MusicPlanVersion = components["schemas"]["MusicPlanVersionOut"];
export type MusicPlanInput = components["schemas"]["MusicPlanSaveIn"];
export type MusicPlanCue = components["schemas"]["CueOut"];
export type MusicPlanCueInput = components["schemas"]["CueIn"];
export type MusicPlanBoundary = components["schemas"]["BoundaryOut"];
export type MusicPlanBoundaryInput = components["schemas"]["BoundaryIn"];
export type MusicPlanAnchor = components["schemas"]["AnchorOut"];
export type MusicPlanAnchorInput = components["schemas"]["AnchorIn"];
export type MusicPlanTimeline = components["schemas"]["TimelineOut"];
export type MusicPlanRound = components["schemas"]["RoundOut"];

/**
 * Every music plan query of a project starts with this key. It also starts with the project's
 * own key, so saving the project's settings (which refreshes the project) refreshes the panel.
 */
export function musicPlanKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "music-plan"] as const;
}

async function fetchMusicPlan(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/music-plan", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the music plan (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the list of versions, the newest job, why it is out of date and what the
 * editor offers. It is loaded again every few seconds while the job is waiting or running.
 */
export function useMusicPlan(projectId: number) {
  return useQuery({
    queryKey: musicPlanKey(projectId),
    queryFn: () => fetchMusicPlan(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

async function fetchMusicPlanVersion(projectId: number, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/music-plan/versions/{version}",
    { params: { path: { project_id: projectId, version } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the version (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** One stored version. Nothing is loaded while `version` is null. */
export function useMusicPlanVersion(projectId: number, version: number | null) {
  return useQuery({
    queryKey: [...musicPlanKey(projectId), "version", version],
    queryFn: () => fetchMusicPlanVersion(projectId, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/**
 * Starts the job that writes the plan and reviews it. `confirmReplaceManual` is true only after
 * the owner agreed to add a version from the model on top of one they wrote.
 */
export function useRunMusicPlan(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-plan/run",
        {
          params: { path: { project_id: projectId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the music plan (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: musicPlanKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Saves the edited music plan as the next version, written by the owner. */
export function useSaveMusicPlan(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (content: MusicPlanInput) => {
      const { data, error, response } = await api.PUT("/api/projects/{project_id}/music-plan", {
        params: { path: { project_id: projectId } },
        body: content,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the music plan (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
