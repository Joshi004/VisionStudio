import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction, useJobs } from "./jobs";
import { SLOW_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type Staleness = components["schemas"]["StalenessOut"];
export type StalenessGroup = components["schemas"]["StalenessGroupOut"];
export type StalenessItem = components["schemas"]["StalenessItemOut"];
export type AcceptStage = components["schemas"]["AcceptIn"]["stage"];

/**
 * The staleness query of a project. It sits under the project's key, so saving the story (which
 * refreshes the project) refreshes the overview too.
 */
export function stalenessKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "staleness"] as const;
}

async function fetchStaleness(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/staleness",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load what is out of date (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * Everything out of date in the project, by step, with the reasons. The answer is expensive to
 * compute, so it is loaded only while something shows it (`enabled`), again every 30 seconds
 * while a job of the project is waiting or running (a job changes what is current), and once
 * more when the last job ends.
 */
export function useStaleness(projectId: number, { enabled = true }: { enabled?: boolean } = {}) {
  const queryClient = useQueryClient();
  const jobs = useJobs(isValidProjectId(projectId) ? projectId : undefined);
  const anyJobActive = jobs.data?.some(isJobActive) ?? false;

  const wasActive = useRef(false);
  useEffect(() => {
    const before = wasActive.current;
    wasActive.current = anyJobActive;
    if (before && !anyJobActive) {
      // Without cancelRefetch, a request already being computed is not started over.
      void queryClient.invalidateQueries(
        { queryKey: stalenessKey(projectId) },
        { cancelRefetch: false },
      );
    }
  }, [anyJobActive, projectId, queryClient]);

  return useQuery({
    queryKey: stalenessKey(projectId),
    queryFn: () => fetchStaleness(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: anyJobActive ? SLOW_POLL_MS : false,
  });
}

type AcceptInput = {
  stage: AcceptStage;
  sceneId?: string | null;
  shotId?: string | null;
};

/**
 * "Accept as is": keeps one out-of-date artifact as it is. The answer is the new overview. The
 * stage panels are loaded again too, because the accepted artifact is a new version.
 */
export function useAcceptAsIs(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: AcceptInput) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/staleness/accept",
        {
          params: { path: { project_id: projectId } },
          body: {
            stage: input.stage,
            scene_id: input.sceneId ?? null,
            shot_id: input.shotId ?? null,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not accept it as it is (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId] }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
