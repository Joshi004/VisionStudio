import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY, type Angle } from "./characterLab";
import { characterImagesKey } from "./characterImages";
import { characterLinksKey } from "./characterLinks";
import { environmentDefinitionsKey } from "./environmentDefinitions";
import { ENVIRONMENT_LAB_KEY } from "./environmentLab";
import { environmentLinksKey } from "./environmentLinks";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { lookStateKey } from "./lookStateResolution";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type LookStateImages = components["schemas"]["LookStateImagesOut"];
export type LookStateImageItem = components["schemas"]["LookStateImageItemOut"];
export type LookStateRunAll = components["schemas"]["LookStateRunAllOut"];

/** Every look-state-images query of a project starts with this key (and the project's own). */
export function lookStateImagesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "look-state-images"] as const;
}

async function fetchImages(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/look-state-images",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the pictures of the new looks and states (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The new looks and environment states of the newest resolution with where each one's
 * pictures stand. It is loaded again every few seconds while any is being made. When the last
 * one finishes, the character or environment has a new version and the project's pin has moved,
 * so the links, the definitions, the character images and the labs are loaded again too.
 */
export function useLookStateImages(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: lookStateImagesKey(projectId),
    queryFn: () => fetchImages(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.items.some((item) => item.status === "in_progress")
        ? ACTIVE_POLL_MS
        : false,
  });

  const anyActive = query.data?.items.some((item) => item.status === "in_progress") ?? false;
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !anyActive) {
      void queryClient.invalidateQueries({ queryKey: characterLinksKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: environmentLinksKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: environmentDefinitionsKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: characterImagesKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: lookStateKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY });
      void queryClient.invalidateQueries({ queryKey: ENVIRONMENT_LAB_KEY });
    }
    wasActive.current = anyActive;
  }, [anyActive, projectId, queryClient]);

  return query;
}

/** A refusal can mean something upstream changed, so the stages it reads are loaded again. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: lookStateImagesKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: lookStateKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: characterImagesKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: environmentDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Make pictures for all": starts every new look and state that has no pictures yet. */
export function useMakeAllLookStateImages(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/look-state-images/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the pictures (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the pictures of one new look (a fresh attempt, also after a failure). */
export function useMakeLookImages(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (recordId: number) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/look-state-images/looks/{record_id}/run",
        { params: { path: { project_id: projectId, record_id: recordId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the pictures (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the picture of one new environment state (also after a failure). */
export function useMakeStateImage(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (recordId: number) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/look-state-images/states/{record_id}/run",
        { params: { path: { project_id: projectId, record_id: recordId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the picture (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Makes one angle of a new look again (the Character lab's own endpoint). */
export function useRedoLookAngle(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { lookId: number; angle: Angle }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/looks/{look_id}/angles/{angle}",
        { params: { path: { look_id: input.lookId, angle: input.angle } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The angle was not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}
