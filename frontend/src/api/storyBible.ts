import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type StoryBibleState = components["schemas"]["StoryBibleState"];
export type StoryBibleOut = components["schemas"]["StoryBibleOut"];
export type StoryBibleVersion = components["schemas"]["StoryBibleVersionOut"];

/**
 * Every Story Bible query of a project starts with this key. It also starts with the project's
 * own key, so saving the story (which refreshes the project) refreshes the "out of date" flag.
 */
export function storyBibleKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "story-bible"] as const;
}

async function fetchStoryBible(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/story-bible", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the Story Bible (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the list of versions, the newest job and the "out of date" flag. It is
 * loaded again every few seconds while the job is waiting or running.
 */
export function useStoryBible(projectId: number) {
  return useQuery({
    queryKey: storyBibleKey(projectId),
    queryFn: () => fetchStoryBible(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

async function fetchStoryBibleVersion(projectId: number, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/story-bible/versions/{version}",
    { params: { path: { project_id: projectId, version } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the version (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** One stored version. Nothing is loaded while `version` is null. */
export function useStoryBibleVersion(projectId: number, version: number | null) {
  return useQuery({
    queryKey: [...storyBibleKey(projectId), "version", version],
    queryFn: () => fetchStoryBibleVersion(projectId, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/** Starts the job that writes the next version from the saved story. */
export function useRunStoryBible(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/story-bible/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the Story Bible (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: storyBibleKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
