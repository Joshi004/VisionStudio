import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";

export type ShotDefinitions = components["schemas"]["ShotDefinitionsOut"];
export type SceneShotDefinitions =
  components["schemas"]["SceneShotDefinitionsOut"];
export type ShotDefinitionEntry =
  components["schemas"]["ShotDefinitionEntryOut"];
export type ShotDefinitionContent =
  components["schemas"]["ShotDefinitionContentOut"];
export type ShotDefinitionsRun =
  components["schemas"]["ShotDefinitionsRunManyOut"];
export type ShotDefinitionInput = components["schemas"]["ShotDefinitionIn"];

/**
 * Every shot-definition query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" state too.
 */
export function shotDefinitionsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "shot-definitions"] as const;
}

async function fetchShotDefinitions(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/shot-definitions",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the shot definitions (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of scenes with where each shot's definition stands. It is loaded again every
 * few seconds while any definition job is waiting or running. (The continuity check queues
 * cut repairs that write definitions of their own, PHASE-023: `useShotContinuity` loads this
 * again while it is busy.)
 */
export function useShotDefinitions(projectId: number) {
  return useQuery({
    queryKey: shotDefinitionsKey(projectId),
    queryFn: () => fetchShotDefinitions(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((scene) =>
        scene.shots.some((shot) => isJobActive(shot.job)),
      )
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** A refusal can mean something changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: shotDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

function startError(error: unknown, status: number): ApiError {
  return new ApiError(
    detailMessage(
      error,
      `Could not start the shot definition (HTTP ${status}).`,
    ),
    status,
  );
}

/** "Define all": starts a job for every shot, in every scene that can be defined, that is missing or out of date. */
export function useDefineAllShots(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-definitions/run",
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

/** Starts the jobs that define every shot of one scene that is missing or out of date. */
export function useDefineSceneShots(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-definitions/{scene_id}/run",
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

/**
 * Starts the job that defines one shot. `confirmReplaceManual` is true only after the user
 * agreed to add a definition from the model on top of one they wrote. `feedback` is the user's
 * note on the newest definition: the shot is then defined again with the note.
 */
export function useDefineOneShot(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (target: {
      sceneId: string;
      shotId: string;
      confirmReplaceManual: boolean;
      feedback?: string;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-definitions/{scene_id}/{shot_id}/run",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: target.sceneId,
              shot_id: target.shotId,
            },
          },
          body: {
            confirm_replace_manual: target.confirmReplaceManual,
            feedback: target.feedback,
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

/** Saves one shot's edited specification as its next version, written by the user. */
export function useSaveShotDefinition(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      sceneId: string;
      shotId: string;
      definition: ShotDefinitionInput;
    }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/shot-definitions/{scene_id}/{shot_id}",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: input.sceneId,
              shot_id: input.shotId,
            },
          },
          body: input.definition,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not save the shot definition (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
