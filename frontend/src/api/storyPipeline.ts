import { useEffect, useRef } from "react";
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

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
export type ReviewPoint = components["schemas"]["ReviewPointOut"];
export type ReviewPointKey = ReviewPoint["key"];
export type PipelineReview = components["schemas"]["ReviewOut"];
export type RejectedTarget = components["schemas"]["RejectedTarget"];
export type PipelineScene = components["schemas"]["PipelineSceneOut"];
export type PipelineLane = components["schemas"]["PipelineLaneOut"];
export type SceneReview = components["schemas"]["SceneReviewOut"];

/**
 * The scenes a run would be limited to and the step it would make again in them (SCN-004).
 * No scenes: the whole story. The server answers what such a run would replace.
 */
export type PipelineSelection = {
  scenes: string[];
  remakeFrom: string | null;
};

const WHOLE_STORY: PipelineSelection = { scenes: [], remakeFrom: null };

/** The pipeline query of a project, under the project's key like the stage panels'. */
export function storyPipelineKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "story-pipeline"] as const;
}

/** The query key of the pipeline for one choice of scenes; no scenes is the project's own key. */
function storyPipelineQueryKey(
  projectId: number,
  selection: PipelineSelection,
) {
  return selection.scenes.length === 0
    ? storyPipelineKey(projectId)
    : ([...storyPipelineKey(projectId), selection] as const);
}

async function fetchStoryPipeline(
  projectId: number,
  selection: PipelineSelection,
) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/story-pipeline",
    {
      params: {
        path: { project_id: projectId },
        query: {
          scenes: selection.scenes,
          remake_from:
            selection.scenes.length > 0 ? selection.remakeFrom : null,
        },
      },
    },
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
    run.review_at ?? "",
    run.scenes.map((scene) => scene.id).join(","),
    ...run.steps.map(
      (step) => `${step.status}:${step.done}/${step.total}/${step.left_alone}`,
    ),
    ...run.lanes.map((lane) => `${lane.status}:${lane.done}`),
    run.jobs_made,
  ].join("|");
}

function storyPipelineOptions(
  projectId: number,
  selection: PipelineSelection,
) {
  return queryOptions({
    queryKey: storyPipelineQueryKey(projectId, selection),
    queryFn: () => fetchStoryPipeline(projectId, selection),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) => {
      const data = current.state.data;
      if (isJobActive(data?.run ?? null)) {
        return ACTIVE_POLL_MS;
      }
      return data !== undefined && !data.can_start ? STATUS_POLL_MS : false;
    },
  });
}

/**
 * Only the state of the pipeline (can a run start, and why not), loaded again like
 * `useStoryPipeline` does but without refreshing the other queries of the project. Many scene
 * rows use it at once, and the panel that owns the run does the refreshing.
 */
export function useStoryPipelineState(projectId: number) {
  return useQuery(storyPipelineOptions(projectId, WHOLE_STORY));
}

/**
 * The pipeline of a project and its newest run. It is loaded again every few seconds while a
 * run is waiting or running, and now and then while a run cannot start because other jobs are
 * going on (so the button wakes up when they end).
 *
 * `selection` (SCN-004) is the scenes a run would be limited to: the answer then lists what
 * that run would replace.
 *
 * Whenever the run's progress changes, every other query of the project is refreshed too: the
 * run makes the same jobs and rows the stage panels show, so each panel catches up at once
 * instead of at its own next poll.
 */
export function useStoryPipeline(
  projectId: number,
  selection: PipelineSelection = WHOLE_STORY,
) {
  const queryClient = useQueryClient();
  const query = useQuery(storyPipelineOptions(projectId, selection));

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
  /** Limits the run to these scenes (their ids). None: the whole story. */
  scenes?: string[];
  /** Makes this step again in those scenes, although it is up to date. */
  remakeFrom?: string | null;
};

async function postRun(projectId: number, options: StartOptions) {
  const { data, error, response } = await api.POST(
    "/api/projects/{project_id}/story-pipeline/run",
    {
      params: { path: { project_id: projectId } },
      body: {
        pause_after: options.pauseAfter,
        confirm_overwrite: options.confirmOverwrite,
        scope: options.scope,
        scenes: options.scenes ?? [],
        remake_from: options.remakeFrom ?? null,
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
}

/** Starts the run. A 409 means there is something to allow first (its message says what). */
export function useStartStoryPipeline(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (options: StartOptions) => postRun(projectId, options),
    // A refusal can mean something changed, so the state and the jobs are loaded again.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: storyPipelineKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

type RunSceneOptions = {
  sceneId: string;
  /** Makes this step of the scene again, although it is up to date. */
  remakeFrom?: string | null;
  /** Allows the run to replace what the user chose or wrote. */
  confirmOverwrite?: boolean;
};

/**
 * Starts a run for one scene (SCN-004): only its targets, the story-wide work that is missing,
 * and a render of the scene at the end. A 409 means there is something to allow first.
 */
export function useRunScene(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (options: RunSceneOptions) =>
      postRun(projectId, {
        pauseAfter: [],
        confirmOverwrite: options.confirmOverwrite ?? false,
        scope: "all",
        scenes: [options.sceneId],
        remakeFrom: options.remakeFrom ?? null,
      }),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: storyPipelineKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * Lets a paused run go on. At a review point, `rejected` lists the targets to make
 * again: the run then waits at the same review point once more.
 */
export function useContinueStoryPipeline(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (rejected: RejectedTarget[] = []) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/story-pipeline/continue",
        {
          params: { path: { project_id: projectId } },
          body: { rejected },
        },
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

/**
 * Answers the review one scene waits at (SCN-010). `rejected` lists the targets of the scene to
 * make again: the scene then waits at the same review point once more. With none the scene is
 * approved and goes on. The run goes on for the other scenes meanwhile.
 */
export function useAnswerSceneReview(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (answer: {
      sceneId: string;
      rejected: RejectedTarget[];
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/story-pipeline/scene-review/{scene_id}",
        {
          params: {
            path: { project_id: projectId, scene_id: answer.sceneId },
          },
          body: { rejected: answer.rejected },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not answer the review (HTTP ${response.status}).`,
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
