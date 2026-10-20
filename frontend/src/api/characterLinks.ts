import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY } from "./characterLab";
import { ApiError, detailMessage } from "./errors";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type CharacterLinks = components["schemas"]["CharacterLinksOut"];
export type LinkEntry = components["schemas"]["LinkEntryOut"];
export type LinkedCharacter = components["schemas"]["LinkedCharacterOut"];
export type OrphanedLink = components["schemas"]["OrphanedLinkOut"];
export type CharacterUsage = components["schemas"]["CharacterUsageOut"];

/**
 * Every character-link query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes it too.
 */
export function characterLinksKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "character-links"] as const;
}

/** The projects that use a character. It sits under the Character lab's key on purpose. */
function usageKey(characterId: number | null) {
  return [...CHARACTER_LAB_KEY, "projects", characterId] as const;
}

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

async function fetchLinks(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/character-links", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the character links");
  }
  return data;
}

/**
 * The newest discovered characters, each with the library character it is linked to (and the
 * version the project pins), and the links that are no longer in the newest list. "A newer
 * version is available" is worked out by the server on every read, so it is loaded again when
 * the window gets focus again, which is how a lab edit shows up here.
 */
export function useCharacterLinks(projectId: number) {
  return useQuery({
    queryKey: characterLinksKey(projectId),
    queryFn: () => fetchLinks(projectId),
    enabled: isValidProjectId(projectId),
  });
}

/**
 * Creating a link can make library characters, and every link changes who uses a character, so
 * the Character lab's queries are marked old as well as the project's links.
 */
function refreshAfterLinkChange(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: characterLinksKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY }),
  ]);
}

/** Makes a library character for every unlinked entry of the newest list. */
export function useLinkAll(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-links/link-all",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The characters were not linked");
      }
      return data;
    },
    onSettled: () => refreshAfterLinkChange(queryClient, projectId),
  });
}

/** Makes a new library character from one entry and pins its version 1. */
export function useCreateLink(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-links/{discovery_id}/create",
        { params: { path: { project_id: projectId, discovery_id: discoveryId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The character was not created");
      }
      return data;
    },
    onSettled: () => refreshAfterLinkChange(queryClient, projectId),
  });
}

/** Links one entry to an existing library character and pins its newest version. */
export function useMapLink(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { discoveryId: string; characterId: number }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/character-links/{discovery_id}",
        {
          params: { path: { project_id: projectId, discovery_id: input.discoveryId } },
          body: { character_id: input.characterId },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The character was not linked");
      }
      return data;
    },
    onSettled: () => refreshAfterLinkChange(queryClient, projectId),
  });
}

/** Removes a link. The library character stays in the Character lab. */
export function useUnlink(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { error, response } = await api.DELETE(
        "/api/projects/{project_id}/character-links/{discovery_id}",
        { params: { path: { project_id: projectId, discovery_id: discoveryId } } },
      );
      // The answer has no body (204), so success is the status and not `data`.
      if (!response.ok) {
        throw failure(error, response.status, "The link was not removed");
      }
    },
    onSettled: () => refreshAfterLinkChange(queryClient, projectId),
  });
}

async function fetchUsage(characterId: number) {
  const { data, error, response } = await api.GET("/api/lab/characters/{character_id}/projects", {
    params: { path: { character_id: characterId } },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the projects");
  }
  return data;
}

/** The story projects that use a library character, with the version each pins. Read-only. */
export function useCharacterProjects(characterId: number | null) {
  return useQuery({
    queryKey: usageKey(characterId),
    queryFn: () => fetchUsage(characterId as number),
    enabled: characterId !== null,
  });
}
