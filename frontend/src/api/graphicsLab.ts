import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import type { components } from "./schema";

export type GraphicRunSummary = components["schemas"]["GraphicRunSummaryOut"];
export type GraphicRun = components["schemas"]["GraphicRunOut"];
export type GraphicRunCreate = components["schemas"]["GraphicRunCreate"];
export type GraphicEngine = components["schemas"]["GraphicEngineOut"];
export type GraphicRender = components["schemas"]["GraphicRenderOut"];
export type GraphicRunState = GraphicRunSummary["state"];
export type GraphicOrientation = GraphicRunSummary["orientation"];
export type GraphicVerdict = NonNullable<GraphicRender["verdict"]>;

const PAGE_SIZE = 20;

/** Every Graphics lab query starts with this key. */
export const GRAPHICS_LAB_KEY = ["lab", "graphics"] as const;
const runsKey = [...GRAPHICS_LAB_KEY, "runs"] as const;

async function fetchRuns(beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/graphics/runs", {
    params: { query: { before_id: beforeId, limit: PAGE_SIZE } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the runs (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The runs, newest first, a page at a time. They are loaded again every few seconds while the
 * brief of any of them is being written, so its state changes by itself.
 */
export function useGraphicsRuns() {
  return useInfiniteQuery({
    queryKey: runsKey,
    queryFn: ({ pageParam }) => fetchRuns(pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE_SIZE ? last[last.length - 1].id : undefined),
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.some((run) => run.state === "writing_brief"))
        ? ACTIVE_POLL_MS
        : false,
  });
}

async function fetchRun(runId: number) {
  const { data, error, response } = await api.GET("/api/lab/graphics/runs/{run_id}", {
    params: { path: { run_id: runId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the run (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** True while a job behind the run (its brief, or any input or render) is waiting or running. */
function hasActiveJob(run: GraphicRun | undefined): boolean {
  if (run === undefined) {
    return false;
  }
  return (
    isJobActive(run.brief_job) ||
    run.engines.some((engine) =>
      engine.renders.some((render) => isJobActive(render.input_job) || isJobActive(render.render_job)),
    )
  );
}

/**
 * One run with its four engines, for the run page. Nothing is loaded while `runId` is null. It
 * is loaded again every few seconds while any job behind it is waiting or running.
 */
export function useGraphicsRun(runId: number | null) {
  return useQuery({
    queryKey: [...GRAPHICS_LAB_KEY, "run", runId],
    queryFn: () => fetchRun(runId as number),
    enabled: runId !== null,
    // A run that does not exist (it was deleted) will not appear on a retry.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
    refetchInterval: (query) => (hasActiveJob(query.state.data) ? ACTIVE_POLL_MS : false),
  });
}

/** Makes a run from a line and an orientation. Nothing is started and nothing is paid for. */
export function useCreateGraphicsRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: GraphicRunCreate) => {
      const { data, error, response } = await api.POST("/api/lab/graphics/runs", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The run was not made (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: runsKey }),
  });
}

/** Records what a person decided after watching a render. Only the fields that are sent change. */
export function useUpdateGraphicsRender() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      renderId: number;
      body: { verdict?: GraphicVerdict | null; note?: string | null };
    }) => {
      const { data, error, response } = await api.PATCH("/api/lab/graphics/renders/{render_id}", {
        params: { path: { render_id: input.renderId } },
        body: input.body,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The verdict was not saved (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // The run page shows every render of the run, so the run is read again.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GRAPHICS_LAB_KEY }),
  });
}
