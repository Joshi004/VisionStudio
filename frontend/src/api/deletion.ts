import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY } from "./characterLab";
import { ENVIRONMENT_LAB_KEY } from "./environmentLab";
import { ApiError, detailMessage } from "./errors";
import { LAB_KEY } from "./imageLab";
import { invalidateAfterJobAction } from "./jobs";
import { MUSIC_LAB_KEY } from "./musicLab";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";
import { VIDEO_LAB_KEY } from "./videoLab";
import { VOICE_LAB_KEY, VOICES_KEY } from "./voiceLab";

export type ProjectDeletionPreview = components["schemas"]["ProjectDeletionPreviewOut"];
export type DeletionItem = components["schemas"]["DeletionItemOut"];
export type LibraryDeletionPreview = components["schemas"]["LibraryDeletionPreviewOut"];
export type ProjectUse = components["schemas"]["ProjectUseOut"];
export type MissingItem = components["schemas"]["MissingItemOut"];
export type LabSampleDeletionPreview = components["schemas"]["LabSampleDeletionPreviewOut"];
/** The kinds of lab sample that can be deleted: image_run, video_run, voice_run, music_run, av_test. */
export type LabSampleKind = LabSampleDeletionPreview["kind"];

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
    queryClient.invalidateQueries({ queryKey: MUSIC_LAB_KEY }),
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

/**
 * Deletes the project and the chosen characters and environments. With `purgeServer` the GPU
 * server is also asked to delete what it still holds for them (best effort, after the answer).
 */
export function useDeleteProject(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      characterIds: number[];
      environmentIds: number[];
      purgeServer: boolean;
    }) => {
      const { error, response } = await api.POST("/api/projects/{project_id}/delete", {
        params: { path: { project_id: projectId } },
        body: {
          character_ids: input.characterIds,
          environment_ids: input.environmentIds,
          purge_server: input.purgeServer,
        },
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

/**
 * Deletes a character for good. The projects that used it are flagged, not changed. With
 * `purgeServer` the GPU server is also cleaned up (best effort, after the answer).
 */
export function useDeleteCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; purgeServer: boolean }) => {
      const { error, response } = await api.DELETE("/api/lab/characters/{character_id}", {
        params: {
          path: { character_id: input.characterId },
          query: { purge_server: input.purgeServer },
        },
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

/**
 * Deletes an environment for good. The projects that used it are flagged, not changed. With
 * `purgeServer` the GPU server is also cleaned up (best effort, after the answer).
 */
export function useDeleteEnvironment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { environmentId: number; purgeServer: boolean }) => {
      const { error, response } = await api.DELETE("/api/lab/environments/{environment_id}", {
        params: {
          path: { environment_id: input.environmentId },
          query: { purge_server: input.purgeServer },
        },
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

// --- Lab samples ------------------------------------------------------------------------------

/**
 * Where a lab sample (an image run, a video run, a speech, a music run or an Audio video test)
 * is still used, and why it cannot be deleted now, if so. It is read when the dialog opens and
 * is never kept: what uses the sample can change at any time.
 */
export function useLabSampleDeletionPreview(kind: LabSampleKind | null, sampleId: number | null) {
  return useQuery({
    queryKey: ["lab", "samples", kind, sampleId, "deletion-preview"],
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/lab/samples/{kind}/{sample_id}/deletion-preview",
        { params: { path: { kind: kind as LabSampleKind, sample_id: sampleId as number } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not load where it is used");
      }
      return data;
    },
    enabled: kind !== null && sampleId !== null,
    gcTime: 0,
  });
}

/**
 * Deletes one lab sample and its file for good. The server refuses (409) while something still
 * uses it. With `purgeServer` the GPU server is also cleaned up (best effort, after the answer).
 */
export function useDeleteLabSample() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { kind: LabSampleKind; sampleId: number; purgeServer: boolean }) => {
      const { error, response } = await api.DELETE("/api/lab/samples/{kind}/{sample_id}", {
        params: {
          path: { kind: input.kind, sample_id: input.sampleId },
          query: { purge_server: input.purgeServer },
        },
      });
      if (!response.ok) {
        throw failure(error, response.status, "The sample was not deleted");
      }
    },
    onSettled: () => {
      void refreshAfterDeletion(queryClient);
    },
  });
}
