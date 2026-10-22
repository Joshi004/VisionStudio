import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ENVIRONMENT_LAB_KEY } from "./environmentLab";
import { environmentLinksKey } from "./environmentLinks";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type EnvironmentDefinitions = components["schemas"]["EnvironmentDefinitionsOut"];
export type EnvironmentDefinitionEntry = components["schemas"]["EnvironmentDefinitionEntryOut"];
export type EnvironmentDefinition = components["schemas"]["EnvironmentDefinitionOut"];
export type EnvironmentDefinitionPicture = components["schemas"]["EnvironmentPictureOut"];
export type EnvironmentDefineAll = components["schemas"]["EnvironmentRunAllOut"];

/**
 * Every environment-definition query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" state too.
 */
export function environmentDefinitionsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "environment-definitions"] as const;
}

/**
 * Is anything still being made for this environment? Its definition job is waiting or running,
 * or its picture is being written or drawn. The stage keeps asking again while that is so.
 */
export function entryIsBusy(entry: EnvironmentDefinitionEntry): boolean {
  return isJobActive(entry.job) || entry.picture.status === "in_progress";
}

async function fetchDefinitions(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/environment-definitions",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the definitions (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of environments with where each definition and picture stands. It is loaded
 * again every few seconds while any definition job or picture is being made. When the last one
 * finishes, a definition has been saved onto a library environment (the pin moved and the
 * profile changed) and its picture was attached, so the project's environment links and the
 * environment library are loaded again too.
 */
export function useEnvironmentDefinitions(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: environmentDefinitionsKey(projectId),
    queryFn: () => fetchDefinitions(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some(entryIsBusy) ? ACTIVE_POLL_MS : false,
  });

  const anyBusy = query.data?.entries.some(entryIsBusy) ?? false;
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !anyBusy) {
      void queryClient.invalidateQueries({ queryKey: environmentLinksKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: ENVIRONMENT_LAB_KEY });
    }
    wasBusy.current = anyBusy;
  }, [anyBusy, projectId, queryClient]);

  return query;
}

/** A refusal can mean the Story Bible changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: environmentDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Define all": starts a job for every linked environment the pipeline made. */
export function useDefineAllEnvironments(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-definitions/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the definitions (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * Starts the job that defines one environment. `confirmOverwrite` is true only after the user
 * agreed to overwrite an environment they chose from the library.
 */
export function useDefineOneEnvironment(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { discoveryId: string; confirmOverwrite: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-definitions/{discovery_id}/run",
        {
          params: { path: { project_id: projectId, discovery_id: input.discoveryId } },
          body: { confirm_overwrite: input.confirmOverwrite },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the definition (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * "Replace picture" (PHASE-039): makes a new canonical picture for an environment that has one.
 * The project moves to a new version, so what used the old picture reads out of date.
 */
export function useReplaceEnvironmentPicture(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-definitions/{discovery_id}/replace-picture",
        { params: { path: { project_id: projectId, discovery_id: discoveryId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not replace the picture (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        refreshAfterRun(queryClient, projectId),
        // The pin moved, so everything that read the old picture is judged again.
        queryClient.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId] }),
      ]),
  });
}

/** Makes the picture of the pinned version again, after a picture failed. */
export function useRetryEnvironmentPicture(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-definitions/{discovery_id}/picture",
        { params: { path: { project_id: projectId, discovery_id: discoveryId } } },
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
