import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { ACTIVE_POLL_MS, STATUS_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type PipelineBoard = components["schemas"]["PipelineBoardOut"];
export type BoardStep = components["schemas"]["BoardStepOut"];
export type BoardStepStatus = BoardStep["status"];
export type BoardRun = components["schemas"]["BoardRunOut"];
export type ProjectActivity = components["schemas"]["ActivityOut"];

/** Both queries sit under the project's key, so whatever refreshes the project refreshes them. */
export function pipelineBoardKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "pipeline-board"] as const;
}

export function activityKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "activity"] as const;
}

async function fetchActivity(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/activity", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the project activity (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

async function fetchPipelineBoard(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/pipeline-board", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the pipeline board (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The cheap "is anything changing" answer: a revision and the job counts. It is asked every few
 * seconds while jobs are going on, and now and then otherwise (a change made in another tab).
 */
export function useProjectActivity(projectId: number) {
  return useQuery({
    queryKey: activityKey(projectId),
    queryFn: () => fetchActivity(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => {
      const data = query.state.data;
      const busy =
        data !== undefined &&
        (data.queued > 0 || data.running > 0 || data.paused > 0 || data.pipeline_active);
      return busy ? ACTIVE_POLL_MS : STATUS_POLL_MS;
    },
  });
}

/**
 * Where every step of the pipeline stands. The board has no timer of its own: it is loaded
 * again only when the activity revision is not the one the board was made at. A board request
 * that is already being computed is not started over.
 */
export function usePipelineBoard(projectId: number) {
  const queryClient = useQueryClient();
  const activity = useProjectActivity(projectId);
  const query = useQuery({
    queryKey: pipelineBoardKey(projectId),
    queryFn: () => fetchPipelineBoard(projectId),
    enabled: isValidProjectId(projectId),
  });

  const activityRevision = activity.data?.revision;
  const boardRevision = query.data?.revision;
  // The newest activity revision the board was already asked to catch up with, so a board that
  // stays behind (for example after a failed request) does not make a request loop.
  const requested = useRef<string | null>(null);

  useEffect(() => {
    if (activityRevision === undefined || boardRevision === undefined) {
      return;
    }
    if (activityRevision === boardRevision || requested.current === activityRevision) {
      return;
    }
    requested.current = activityRevision;
    void queryClient.invalidateQueries(
      { queryKey: pipelineBoardKey(projectId) },
      { cancelRefetch: false },
    );
  }, [activityRevision, boardRevision, projectId, queryClient]);

  return { ...query, activity: activity.data };
}
