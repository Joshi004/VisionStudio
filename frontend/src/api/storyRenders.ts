import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId } from "./projects";
import type { components } from "./schema";
import { shotTakesKey } from "./shotTakes";

export type StoryRenders = components["schemas"]["StoryRendersOut"];
export type StoryRender = components["schemas"]["StoryRenderOut"];
export type RenderTake = components["schemas"]["RenderTakeOut"];
export type RenderWarning = components["schemas"]["RenderWarningOut"];

/**
 * The story-render query of a project. It starts with the shot takes' key, so whatever
 * refreshes those (generating a clip, selecting a take) refreshes this too: the video is made
 * from the selected takes.
 */
export function storyRendersKey(projectId: number) {
  return [...shotTakesKey(projectId), "story-renders"] as const;
}

async function fetchStoryRenders(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/story-renders",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the story video (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The renders of a project, newest first, and whether another can be made. Nothing is rendered
 * by itself, so the page asks again only while a render job is waiting or running.
 */
export function useStoryRenders(projectId: number) {
  return useQuery({
    queryKey: storyRendersKey(projectId),
    queryFn: () => fetchStoryRenders(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      isJobActive(current.state.data?.job ?? null) ? ACTIVE_POLL_MS : false,
  });
}

/** Starts the job that puts the selected clips and the narration into one video. */
export function useRenderStory(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/story-renders/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the render (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean something changed, so the state and the jobs are loaded again.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: storyRendersKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
