import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY, type Angle } from "./characterLab";
import { characterDefinitionsKey } from "./characterDefinitions";
import { characterLinksKey } from "./characterLinks";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type CharacterImages = components["schemas"]["CharacterImagesOut"];
export type ImageEntry = components["schemas"]["ImageEntryOut"];
export type ImageRunAll = components["schemas"]["ImageRunAllOut"];

/** Every character-images query of a project starts with this key (and the project's own). */
export function characterImagesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "character-images"] as const;
}

async function fetchImages(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/character-images",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the character images (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of characters with where each one's canonical images stand. It is loaded
 * again every few seconds while any look is being made. When the last one finishes, a look has
 * become the character's current look and the project's pin has moved, so the character links,
 * the definitions and the Character lab are loaded again too.
 */
export function useCharacterImages(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: characterImagesKey(projectId),
    queryFn: () => fetchImages(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((entry) => entry.status === "in_progress")
        ? ACTIVE_POLL_MS
        : false,
  });

  const anyActive = query.data?.entries.some((entry) => entry.status === "in_progress") ?? false;
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !anyActive) {
      void queryClient.invalidateQueries({ queryKey: characterLinksKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: characterDefinitionsKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY });
    }
    wasActive.current = anyActive;
  }, [anyActive, projectId, queryClient]);

  return query;
}

/** A refusal can mean the definition changed, so the definitions are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: characterImagesKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: characterDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Make images for all": starts a look for every defined character that needs images. */
export function useMakeAllImages(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-images/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the images (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * Starts the look of one character (a fresh one, also after a failure). `confirmOverwrite` is
 * true only after the user agreed to change a character they chose from the library.
 */
export function useMakeOneImages(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { discoveryId: string; confirmOverwrite: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-images/{discovery_id}/run",
        {
          params: { path: { project_id: projectId, discovery_id: input.discoveryId } },
          body: { confirm_overwrite: input.confirmOverwrite },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the images (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Makes one angle of a look again (the Character lab's own endpoint). */
export function useRedoImageAngle(projectId: number) {
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
