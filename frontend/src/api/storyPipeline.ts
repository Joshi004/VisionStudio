import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, STATUS_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type StoryPipeline = components["schemas"]["StoryPipelineOut"];
export type PipelineRun = components["schemas"]["PipelineRunOut"];
export type PipelineStep = components["schemas"]["PipelineStepOut"];
export type PipelineStepProgress =
  components["schemas"]["PipelineStepProgressOut"];
export type PipelineProblem = components["schemas"]["PipelineProblemOut"];
export type PipelineConfirmation =
  components["schemas"]["PipelineConfirmationOut"];

/** The pipeline query of a project, under the project's key like the stage panels'. */
export function storyPipelineKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "story-pipeline"] as const;
}

async function fetchStoryPipeline(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/story-pipeline",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the pipeline (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/** What changes while a run goes on: its status, phase and every step's progress. */
function runSignature(run: PipelineRun | null | undefined): string | null {
  if (run === null || run === undefined) {
    return null;
  }
  return [
    run.job_id,
    run.status,
    run.phase ?? "",
    run.paused_at ?? "",
    ...run.steps.map(
      (step) => `${step.status}:${step.done}/${step.total}/${step.left_alone}`,
    ),
    run.jobs_made,
  ].join("|");
}

/**
 * The pipeline of a project and its newest run. It is loaded again every few seconds while a
 * run is waiting or running, and now and then while a run cannot start because other jobs are
 * going on (so the button wakes up when they end).
 *
 * Whenever the run's progress changes, every other query of the project is refreshed too: the
 * run makes the same jobs and rows the stage panels show, so each panel catches up at once
 * instead of at its own next poll.
 */
export function useStoryPipeline(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: storyPipelineKey(projectId),
    queryFn: () => fetchStoryPipeline(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) => {
      const data = current.state.data;
      if (isJobActive(data?.run ?? null)) {
        return ACTIVE_POLL_MS;
      }
      return data !== undefined && !data.can_start ? STATUS_POLL_MS : false;
    },
  });

  const signature = runSignature(query.data?.run);
  const seen = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const previous = seen.current;
    seen.current = signature;
    // The first answer only says where the run is; the panels have loaded already.
    if (previous === undefined || previous === signature) {
      return;
    }
    void queryClient.invalidateQueries({
      queryKey: [...PROJECTS_KEY, projectId],
      predicate: (item) => item.queryKey[3] !== "story-pipeline",
    });
    void invalidateAfterJobAction(queryClient);
  }, [signature, projectId, queryClient]);

  return query;
}

/** What a run makes: everything not up to date, or only what is out of date. */
export type PipelineScope = components["schemas"]["PipelineRunBody"]["scope"];

type StartOptions = {
  /** The keys of the steps to pause after. */
  pauseAfter: string[];
  /** Allows the run to replace what the user chose or wrote. */
  confirmOverwrite: boolean;
  /** `out_of_date` regenerates only what exists and is out of date. */
  scope: PipelineScope;
};

/** Starts the run. A 409 means there is something to allow first (its message says what). */
export function useStartStoryPipeline(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (options: StartOptions) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/story-pipeline/run",
        {
          params: { path: { project_id: projectId } },
          body: {
            pause_after: options.pauseAfter,
            confirm_overwrite: options.confirmOverwrite,
            scope: options.scope,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the pipeline (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean something changed, so the state and the jobs are loaded again.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: storyPipelineKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Lets a paused run go on. */
export function useContinueStoryPipeline(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/story-pipeline/continue",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not continue the pipeline (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: storyPipelineKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
