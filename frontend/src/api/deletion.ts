import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY } from "./characterLab";
import { ENVIRONMENT_LAB_KEY } from "./environmentLab";
import { ApiError, detailMessage } from "./errors";
import { LAB_KEY } from "./imageLab";
import { invalidateAfterJobAction } from "./jobs";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";
import { VIDEO_LAB_KEY } from "./videoLab";
import { VOICE_LAB_KEY, VOICES_KEY } from "./voiceLab";

export type ProjectDeletionPreview = components["schemas"]["ProjectDeletionPreviewOut"];
export type DeletionItem = components["schemas"]["DeletionItemOut"];
export type LibraryDeletionPreview = components["schemas"]["LibraryDeletionPreviewOut"];
export type ProjectUse = components["schemas"]["ProjectUseOut"];
export type MissingItem = components["schemas"]["MissingItemOut"];

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

/**
 * A deletion removes projects, library items and the pictures, speech and clips of the labs,
 * and flags the projects that used a deleted item, so every list that could show any of them is
 * marked old.
 */
function refreshAfterDeletion(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: PROJECTS_KEY }),
    queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: ENVIRONMENT_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VOICE_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VIDEO_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VOICES_KEY }),
    invalidateAfterJobAction(queryClient),
  ]);
}

// --- Projects ---------------------------------------------------------------------------------

/**
 * The characters and environments a project used, and the other projects that use them too.
 * It is read when the dialog opens and is never kept: what other projects use can change at any
 * time.
 */
export function useProjectDeletionPreview(projectId: number | null) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, "deletion-preview"],
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/projects/{project_id}/deletion-preview",
        { params: { path: { project_id: projectId as number } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not load what the project uses");
      }
      return data;
    },
    enabled: projectId !== null && isValidProjectId(projectId),
    gcTime: 0,
  });
}

/** Deletes the project and the chosen characters and environments. */
export function useDeleteProject(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterIds: number[]; environmentIds: number[] }) => {
      const { error, response } = await api.POST("/api/projects/{project_id}/delete", {
        params: { path: { project_id: projectId } },
        body: { character_ids: input.characterIds, environment_ids: input.environmentIds },
      });
      // The answer has no body (204), so success is the status and not `data`.
      if (!response.ok) {
        throw failure(error, response.status, "The project was not deleted");
      }
    },
    // What is stored for the project is gone: forget it instead of loading it again.
    onSuccess: () => queryClient.removeQueries({ queryKey: [...PROJECTS_KEY, projectId] }),
    // Not awaited: the page of the deleted item is left as soon as the answer comes, before the
    // lists are loaded again (loading its own page again would only find a 404).
    onSettled: () => {
      void refreshAfterDeletion(queryClient);
    },
  });
}

// --- Library characters and environments ------------------------------------------------------

/** The projects that use a character, and why it cannot be deleted now, if so. */
export function useCharacterDeletionPreview(characterId: number | null) {
  return useQuery({
    queryKey: [...CHARACTER_LAB_KEY, "deletion-preview", characterId],
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/lab/characters/{character_id}/deletion-preview",
        { params: { path: { character_id: characterId as number } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not load the projects");
      }
      return data;
    },
    enabled: characterId !== null,
    gcTime: 0,
  });
}

/** Deletes a character for good. The projects that used it are flagged, not changed. */
export function useDeleteCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (characterId: number) => {
      const { error, response } = await api.DELETE("/api/lab/characters/{character_id}", {
        params: { path: { character_id: characterId } },
      });
      if (!response.ok) {
        throw failure(error, response.status, "The character was not deleted");
      }
    },
    // Not awaited: the page of the deleted item is left as soon as the answer comes, before the
    // lists are loaded again (loading its own page again would only find a 404).
    onSettled: () => {
      void refreshAfterDeletion(queryClient);
    },
  });
}

/** The projects that use an environment, and why it cannot be deleted now, if so. */
export function useEnvironmentDeletionPreview(environmentId: number | null) {
  return useQuery({
    queryKey: [...ENVIRONMENT_LAB_KEY, "deletion-preview", environmentId],
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/lab/environments/{environment_id}/deletion-preview",
        { params: { path: { environment_id: environmentId as number } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not load the projects");
      }
      return data;
    },
    enabled: environmentId !== null,
    gcTime: 0,
  });
}

/** Deletes an environment for good. The projects that used it are flagged, not changed. */
export function useDeleteEnvironment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (environmentId: number) => {
      const { error, response } = await api.DELETE("/api/lab/environments/{environment_id}", {
        params: { path: { environment_id: environmentId } },
      });
      if (!response.ok) {
        throw failure(error, response.status, "The environment was not deleted");
      }
    },
    // Not awaited: the page of the deleted item is left as soon as the answer comes, before the
    // lists are loaded again (loading its own page again would only find a 404).
    onSettled: () => {
      void refreshAfterDeletion(queryClient);
    },
  });
}
