import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId } from "./projects";
import type { components } from "./schema";
import { useShotDefinitions } from "./shotDefinitions";
import { shotReferencesKey } from "./shotReferences";

export type GenerationRequests = components["schemas"]["GenerationRequestsOut"];
export type SceneGenerationRequests =
  components["schemas"]["SceneGenerationRequestsOut"];
export type GenerationRequestEntry =
  components["schemas"]["GenerationRequestEntryOut"];
export type RequestPicture = components["schemas"]["RequestPictureOut"];
export type RequestAudio = components["schemas"]["RequestAudioOut"];
export type GenerationRequestsRun =
  components["schemas"]["GenerationRequestsRunOut"];

/**
 * How long the requests keep being asked for after a definition job last ran. The server plans a
 * shot's request a moment after its references are chosen, which is a moment after its
 * definition job finishes, so the page must not stop asking the instant nothing runs.
 */
const GRACE_MS = 15_000;

/**
 * The generation-request query of a project. It starts with the shot references' key (and so
 * the shot definitions'), so whatever refreshes those (pressing Define or Select references,
 * saving the story) refreshes this too: a request is planned from its shot's references.
 */
export function generationRequestsKey(projectId: number) {
  return [...shotReferencesKey(projectId), "requests"] as const;
}

async function fetchGenerationRequests(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/generation-requests",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the generation requests (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * Where each shot's generation request stands. A request is planned by the server right after
 * a shot's references are chosen, so it is loaded again every few seconds while any definition
 * job is waiting or running, and for a short while after.
 */
export function useGenerationRequests(projectId: number) {
  const lastActive = useRef(0);
  const definitionsActive =
    useShotDefinitions(projectId).data?.entries.some((scene) =>
      scene.shots.some((shot) => isJobActive(shot.job)),
    ) ?? false;
  return useQuery({
    queryKey: generationRequestsKey(projectId),
    queryFn: () => fetchGenerationRequests(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: () => {
      if (definitionsActive) {
        lastActive.current = Date.now();
        return ACTIVE_POLL_MS;
      }
      return Date.now() - lastActive.current < GRACE_MS
        ? ACTIVE_POLL_MS
        : false;
    },
  });
}

function refresh(queryClient: QueryClient, projectId: number) {
  return queryClient.invalidateQueries({
    queryKey: generationRequestsKey(projectId),
  });
}

function startError(error: unknown, status: number): ApiError {
  return new ApiError(
    detailMessage(error, `Could not plan the requests (HTTP ${status}).`),
    status,
  );
}

/** "Plan all": plans the request of every shot that has none or an out of date one. */
export function usePlanAllRequests(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/generation-requests/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw startError(error, response.status);
      }
      return data;
    },
    onSettled: () => refresh(queryClient, projectId),
  });
}

/** Plans the request of every shot of one scene that has none or an out of date one. */
export function usePlanSceneRequests(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/generation-requests/{scene_id}/run",
        { params: { path: { project_id: projectId, scene_id: sceneId } } },
      );
      if (!data) {
        throw startError(error, response.status);
      }
      return data;
    },
    onSettled: () => refresh(queryClient, projectId),
  });
}

/** Plans the request of one shot. */
export function usePlanOneShotRequest(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (target: { sceneId: string; shotId: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/generation-requests/{scene_id}/{shot_id}/run",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: target.sceneId,
              shot_id: target.shotId,
            },
          },
        },
      );
      if (!data) {
        throw startError(error, response.status);
      }
      return data;
    },
    onSettled: () => refresh(queryClient, projectId),
  });
}