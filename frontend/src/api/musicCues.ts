import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { musicPlanKey } from "./musicPlan";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type MusicCuesState = components["schemas"]["MusicCuesState"];
export type MusicCueEntry = components["schemas"]["MusicCueEntryOut"];
export type MusicCueVersion = components["schemas"]["MusicCueVersionOut"];
export type MusicCueDetail = components["schemas"]["DetailOut"];
export type MusicCueItem = components["schemas"]["ItemOut"];
export type MusicCueWording = components["schemas"]["WordingOut"];
export type MusicCuesAudit = components["schemas"]["AuditOut"];

/**
 * Every music cues query of a project starts with this key. It also starts with the project's
 * own key, so saving the project's settings (which refreshes the project) refreshes the panel.
 */
export function musicCuesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "music-cues"] as const;
}

async function fetchMusicCues(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/music-cues", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the music cues (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** Whether a cue job, the audit or the plan's revision is waiting or running. */
function anyActive(state: MusicCuesState | undefined): boolean {
  if (!state) return false;
  return (
    state.audit_active ||
    state.revision_active ||
    state.cues.some((entry) => entry.active || isJobActive(entry.job))
  );
}

/**
 * The newest plan's cues with their detail, prompts, objections and the audit. It is loaded
 * again every few seconds while any job of the stage is waiting or running.
 */
export function useMusicCues(projectId: number) {
  return useQuery({
    queryKey: musicCuesKey(projectId),
    queryFn: () => fetchMusicCues(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (anyActive(query.state.data) ? ACTIVE_POLL_MS : false),
  });
}

/**
 * Starts a job for every cue without a current detail, or for one cue (`cueId`) even when it
 * is current.
 */
export function useRunMusicCues(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { cueId?: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-cues/run",
        {
          params: {
            path: { project_id: projectId },
            query: { cue_id: input.cueId },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the cue details (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: musicCuesKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Starts the audit of every cue's prompts. */
export function useAuditMusicCues(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-cues/audit",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the audit (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: musicCuesKey(projectId) }),
        queryClient.invalidateQueries({ queryKey: musicPlanKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
