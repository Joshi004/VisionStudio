import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { characterDefinitionsKey } from "./characterDefinitions";
import { characterImagesKey } from "./characterImages";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type CharacterRelations = components["schemas"]["CharacterRelationsOut"];
export type Relation = components["schemas"]["RelationOut"];
export type RelationKind = Relation["kind"];
/** What a user may write: the two kinds that are stored the other way round are accepted too. */
export type RelationInput = components["schemas"]["RelationIn"];

/**
 * Every character-relations query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" state too.
 */
export function characterRelationsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "character-relations"] as const;
}

async function fetchRelations(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/character-relations",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the relations (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The relations between the story's characters, with where they stand. They are loaded again
 * every few seconds while the job is waiting or running. When it finishes, the definitions and
 * the images (which read the relations) are loaded again too.
 */
export function useCharacterRelations(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: characterRelationsKey(projectId),
    queryFn: () => fetchRelations(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      isJobActive(current.state.data?.job) ? ACTIVE_POLL_MS : false,
  });

  const active = isJobActive(query.data?.job);
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !active) {
      void refreshDependents(queryClient, projectId);
    }
    wasActive.current = active;
  }, [active, projectId, queryClient]);

  return query;
}

/** The stages that read the relations: a change here changes what they say is out of date. */
function refreshDependents(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: characterDefinitionsKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: characterImagesKey(projectId) }),
  ]);
}

/**
 * Starts the job that finds the relations. `confirmReplaceManual` is true only after the user
 * agreed to add a version from the model on top of a list they wrote.
 */
export function useFindRelations(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-relations/run",
        {
          params: { path: { project_id: projectId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the relations search (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean the Story Bible or the characters are out of date, so the jobs are
    // loaded again too, whether the run started or not.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: characterRelationsKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Saves the whole edited list as the next version, written by the user. */
export function useSaveRelations(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (relations: RelationInput[]) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/character-relations",
        { params: { path: { project_id: projectId } }, body: { relations } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the relations (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(characterRelationsKey(projectId), data);
      return refreshDependents(queryClient, projectId);
    },
  });
}
