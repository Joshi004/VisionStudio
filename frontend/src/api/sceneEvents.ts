import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";

export type SceneEvents = components["schemas"]["SceneEventsOut"];
export type SceneEventsEntry = components["schemas"]["SceneEventsEntryOut"];
export type SceneEventsContent = components["schemas"]["SceneEventsContentOut"];
export type SceneEvent = components["schemas"]["SceneEventOut"];
export type SceneEventInput = components["schemas"]["SceneEventIn"];
export type SceneExtractAll = components["schemas"]["SceneEventsRunAllOut"];

/**
 * Every scene-events query of a project starts with this key. It also starts with the project's
 * own key, so saving the story (which refreshes the project) refreshes the "out of date" state
 * too.
 */
export function sceneEventsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "scene-events"] as const;
}

async function fetchEvents(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/scene-events",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the scene events (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of scenes with where each scene's events stand. It is loaded again every few
 * seconds while any extraction job is waiting or running.
 */
export function useSceneEvents(projectId: number) {
  return useQuery({
    queryKey: sceneEventsKey(projectId),
    queryFn: () => fetchEvents(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((entry) => isJobActive(entry.job))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** A refusal can mean something changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: sceneEventsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Extract all": starts a job for every defined scene whose events are missing or out of date. */
export function useExtractAllEvents(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scene-events/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the event extraction (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * Starts the job that extracts the events of one scene. `confirmReplaceManual` is true only
 * after the user agreed to add a version from the model on top of one they wrote.
 */
export function useExtractOneSceneEvents(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scene-events/{scene_id}/run",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the event extraction (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Saves one scene's edited events as its next version, written by the user. */
export function useSaveSceneEvents(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; events: SceneEventInput[] }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/scene-events/{scene_id}",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: { events: input.events },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the scene events (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
