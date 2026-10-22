import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";
import { shotDefinitionsKey, useShotDefinitions } from "./shotDefinitions";

export type ShotReferences = components["schemas"]["ShotReferencesOut"];
export type SceneShotReferences =
  components["schemas"]["SceneShotReferencesOut"];
export type ShotReferenceEntry = components["schemas"]["ShotReferenceEntryOut"];
export type ReferencePicture = components["schemas"]["ReferencePictureOut"];
export type ShotReferenceManifest =
  components["schemas"]["ShotReferenceManifestOut"];
export type CatalogPicture = components["schemas"]["CatalogPictureOut"];
export type ShotReferencesRun = components["schemas"]["ShotReferencesRunOut"];

/**
 * How long the manifests keep being asked for after a definition job last ran. The server
 * chooses a shot's references a moment after its definition job finishes, so the page must not
 * stop asking the instant nothing runs.
 */
const GRACE_MS = 15_000;

/**
 * The reference-manifest query of a project. It starts with the shot definitions' key, so
 * whatever refreshes the definitions (pressing Define, saving the story) refreshes this too: a
 * manifest is worked out from its shot's definition.
 */
export function shotReferencesKey(projectId: number) {
  return [...shotDefinitionsKey(projectId), "references"] as const;
}

async function fetchShotReferences(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/shot-references",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the shot references (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * Where each shot's reference manifest stands. A manifest is chosen by the server right after a
 * shot is defined (by rule at once, or by a job of the language model), so it is loaded again
 * every few seconds while any definition job or any selection job is waiting or running, and
 * for a short while after.
 */
export function useShotReferences(projectId: number) {
  const lastActive = useRef(0);
  const definitionsActive =
    useShotDefinitions(projectId).data?.entries.some((scene) =>
      scene.shots.some((shot) => isJobActive(shot.job)),
    ) ?? false;
  return useQuery({
    queryKey: shotReferencesKey(projectId),
    queryFn: () => fetchShotReferences(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => {
      const selecting =
        query.state.data?.entries.some((scene) =>
          scene.shots.some((shot) => isJobActive(shot.job)),
        ) ?? false;
      if (definitionsActive || selecting) {
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
    queryKey: shotReferencesKey(projectId),
  });
}

function startError(error: unknown, status: number): ApiError {
  return new ApiError(
    detailMessage(
      error,
      `Could not choose the references (HTTP ${status}).`,
    ),
    status,
  );
}

/** "Select all": chooses the references of every shot that has none or an out of date manifest. */
export function useSelectAllReferences(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-references/run",
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

/** Chooses the references of every shot of one scene that has none or an out of date manifest. */
export function useSelectSceneReferences(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-references/{scene_id}/run",
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

/**
 * Chooses the references of one shot. `confirmReplaceManual` is true only after the user agreed
 * to replace a choice of pictures they made.
 */
export function useSelectOneShotReferences(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (target: {
      sceneId: string;
      shotId: string;
      confirmReplaceManual: boolean;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-references/{scene_id}/{shot_id}/run",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: target.sceneId,
              shot_id: target.shotId,
            },
          },
          body: { confirm_replace_manual: target.confirmReplaceManual },
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

/** Saves the user's own choice of pictures for one shot, in the order given, as its next manifest. */
export function useSaveShotReferences(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      sceneId: string;
      shotId: string;
      labImageIds: number[];
    }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/shot-references/{scene_id}/{shot_id}",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: input.sceneId,
              shot_id: input.shotId,
            },
          },
          body: { lab_image_ids: input.labImageIds },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not save the references (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
