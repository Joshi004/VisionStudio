import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ENVIRONMENT_LAB_KEY } from "./environmentLab";
import { ApiError, detailMessage } from "./errors";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type EnvironmentLinks = components["schemas"]["EnvironmentLinksOut"];
export type EnvironmentLinkEntry = components["schemas"]["EnvironmentLinkEntryOut"];
export type LinkedEnvironment = components["schemas"]["LinkedEnvironmentOut"];
export type OrphanedEnvironmentLink = components["schemas"]["OrphanedEnvironmentLinkOut"];
export type EnvironmentUsage = components["schemas"]["EnvironmentUsageOut"];

/**
 * Every environment-link query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes it too.
 */
export function environmentLinksKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "environment-links"] as const;
}

/** The projects that use an environment. It sits under the environment library's key on purpose. */
function usageKey(environmentId: number | null) {
  return [...ENVIRONMENT_LAB_KEY, "projects", environmentId] as const;
}

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

async function fetchLinks(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/environment-links", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the environment links");
  }
  return data;
}

/**
 * The newest discovered environments, each with the library environment it is linked to (and the
 * version the project pins), and the links that are no longer in the newest list. "A newer
 * version is available" is worked out by the server on every read, so it is loaded again when
 * the window gets focus again, which is how a lab edit shows up here.
 */
export function useEnvironmentLinks(projectId: number) {
  return useQuery({
    queryKey: environmentLinksKey(projectId),
    queryFn: () => fetchLinks(projectId),
    enabled: isValidProjectId(projectId),
  });
}

/**
 * Creating a link can make library environments, and every link changes who uses an
 * environment, so the environment library's queries are marked old as well as the project's links.
 */
function refreshAfterLinkChange(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: environmentLinksKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: ENVIRONMENT_LAB_KEY }),
  ]);
}

/** Makes a library environment for every unlinked entry of the newest list. */
export function useLinkAllEnvironments(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-links/link-all",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The environments were not linked");
      }
      return data;
    },
    onSettled: () => refreshAfterLinkChange(queryClient, projectId),
  });
}

/** Makes a new library environment from one entry and pins its version 1. */
export function useCreateEnvironmentLink(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-links/{discovery_id}/create",
        { params: { path: { project_id: projectId, discovery_id: discoveryId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The environment was not created");
      }
      return data;
    },
    onSettled: () => refreshAfterLinkChange(queryClient, projectId),
  });
}

/** Links one entry to an existing library environment and pins its newest version. */
export function useMapEnvironmentLink(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { discoveryId: string; environmentId: number }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/environment-links/{discovery_id}",
        {
          params: { path: { project_id: projectId, discovery_id: input.discoveryId } },
          body: { environment_id: input.environmentId },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The environment was not linked");
      }
      return data;
    },
    onSettled: () => refreshAfterLinkChange(queryClient, projectId),
  });
}

/** Removes a link. The library environment stays in the Character Lab. */
export function useUnlinkEnvironment(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { error, response } = await api.DELETE(
        "/api/projects/{project_id}/environment-links/{discovery_id}",
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

async function fetchUsage(environmentId: number) {
  const { data, error, response } = await api.GET(
    "/api/lab/environments/{environment_id}/projects",
    { params: { path: { environment_id: environmentId } } },
  );
  if (!data) {
    throw failure(error, response.status, "Could not load the projects");
  }
  return data;
}

/** The story projects that use a library environment, with the version each pins. Read-only. */
export function useEnvironmentProjects(environmentId: number | null) {
  return useQuery({
    queryKey: usageKey(environmentId),
    queryFn: () => fetchUsage(environmentId as number),
    enabled: environmentId !== null,
  });
}
