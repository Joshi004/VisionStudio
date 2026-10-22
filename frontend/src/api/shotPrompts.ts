import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { generationRequestsKey } from "./generationRequests";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId } from "./projects";
import type { components } from "./schema";
import { useShotDefinitions } from "./shotDefinitions";

export type ShotPrompts = components["schemas"]["ShotPromptsOut"];
export type SceneShotPrompts = components["schemas"]["SceneShotPromptsOut"];
export type ShotPromptEntry = components["schemas"]["ShotPromptEntryOut"];
export type ShotPromptContent = components["schemas"]["ShotPromptContentOut"];
export type PromptSubject = components["schemas"]["PromptSubjectOut"];
export type PromptSpeaker = components["schemas"]["PromptSpeakerOut"];
export type ShotPromptsRun = components["schemas"]["ShotPromptsRunManyOut"];

/**
 * How long the prompts keep being asked for after a definition job last ran. The server queues
 * a shot's compile job a moment after its request is planned, which is a moment after its
 * definition job finishes, so the page must not stop asking the instant nothing runs.
 */
const GRACE_MS = 15_000;

/**
 * The shot-prompt query of a project. It starts with the generation requests' key (and so the
 * shot references' and the shot definitions'), so whatever refreshes those (pressing Define,
 * Select references or Plan, saving the story) refreshes this too: a prompt is compiled from
 * its shot's request.
 */
export function shotPromptsKey(projectId: number) {
  return [...generationRequestsKey(projectId), "prompts"] as const;
}

async function fetchShotPrompts(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/shot-prompts",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the shot prompts (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * Where each shot's compiled prompt stands. A compile job is queued by the server right after a
 * shot's request is planned, so it is loaded again every few seconds while a compile job (or a
 * definition job) is waiting or running, and for a short while after.
 */
export function useShotPrompts(projectId: number) {
  const lastActive = useRef(0);
  const definitionsActive =
    useShotDefinitions(projectId).data?.entries.some((scene) =>
      scene.shots.some((shot) => isJobActive(shot.job)),
    ) ?? false;
  return useQuery({
    queryKey: shotPromptsKey(projectId),
    queryFn: () => fetchShotPrompts(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) => {
      const promptsActive =
        current.state.data?.entries.some((scene) =>
          scene.shots.some((shot) => isJobActive(shot.job)),
        ) ?? false;
      if (promptsActive || definitionsActive) {
        lastActive.current = Date.now();
        return ACTIVE_POLL_MS;
      }
      return Date.now() - lastActive.current < GRACE_MS
        ? ACTIVE_POLL_MS
        : false;
    },
  });
}

/** A refusal can mean something changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: shotPromptsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

function startError(error: unknown, status: number): ApiError {
  return new ApiError(
    detailMessage(error, `Could not start the shot prompt (HTTP ${status}).`),
    status,
  );
}

/** "Compile all": starts a job for every shot that has a planned request and no current prompt. */
export function useCompileAllPrompts(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-prompts/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw startError(error, response.status);
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the jobs that compile every shot of one scene that has no current prompt. */
export function useCompileScenePrompts(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-prompts/{scene_id}/run",
        { params: { path: { project_id: projectId, scene_id: sceneId } } },
      );
      if (!data) {
        throw startError(error, response.status);
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the job that compiles one shot's prompt. */
export function useCompileOnePrompt(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (target: { sceneId: string; shotId: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-prompts/{scene_id}/{shot_id}/run",
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
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}
