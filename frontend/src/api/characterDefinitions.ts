import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY } from "./characterLab";
import { characterLinksKey } from "./characterLinks";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type CharacterDefinitions = components["schemas"]["CharacterDefinitionsOut"];
export type DefinitionEntry = components["schemas"]["DefinitionEntryOut"];
export type CharacterDefinition = components["schemas"]["CharacterDefinitionOut"];
export type DefinitionRunAll = components["schemas"]["RunAllOut"];

/**
 * Every character-definition query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" state too.
 */
export function characterDefinitionsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "character-definitions"] as const;
}

async function fetchDefinitions(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/character-definitions",
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
 * The newest list of characters with where each definition stands. It is loaded again every few
 * seconds while any definition job is waiting or running. When the last one finishes, a
 * definition has been saved onto a library character (the pin moved and the profile changed), so
 * the project's character links and the Character lab are loaded again too.
 */
export function useCharacterDefinitions(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: characterDefinitionsKey(projectId),
    queryFn: () => fetchDefinitions(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((entry) => isJobActive(entry.job))
        ? ACTIVE_POLL_MS
        : false,
  });

  const anyActive = query.data?.entries.some((entry) => isJobActive(entry.job)) ?? false;
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !anyActive) {
      void queryClient.invalidateQueries({ queryKey: characterLinksKey(projectId) });
      void queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY });
    }
    wasActive.current = anyActive;
  }, [anyActive, projectId, queryClient]);

  return query;
}

/** A refusal can mean the Story Bible changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: characterDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Define all": starts a job for every linked character the pipeline made. */
export function useDefineAll(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-definitions/run",
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
 * Starts the job that defines one character. `confirmOverwrite` is true only after the user
 * agreed to overwrite a character they chose from the library.
 */
export function useDefineOne(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { discoveryId: string; confirmOverwrite: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-definitions/{discovery_id}/run",
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
