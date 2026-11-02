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
export type GraphicVoice = components["schemas"]["GraphicVoiceOut"];
export type GraphicVoiceStage = GraphicVoice["state"];
export type GraphicBrief = components["schemas"]["GraphicBriefOut"];
export type GraphicResolved = components["schemas"]["GraphicResolvedOut"];
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
 * brief of any of them is being written or its voice is being made, so its state changes by
 * itself.
 */
export function useGraphicsRuns() {
  return useInfiniteQuery({
    queryKey: runsKey,
    queryFn: ({ pageParam }) => fetchRuns(pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE_SIZE ? last[last.length - 1].id : undefined),
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) =>
        page.some((run) => run.state === "writing_brief" || run.state === "making_voice"),
      )
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

/**
 * True while a job behind the run (its speech, the timing of its words, its brief, or any input
 * or render) is waiting or running.
 */
function hasActiveJob(run: GraphicRun | undefined): boolean {
  if (run === undefined) {
    return false;
  }
  return (
    isJobActive(run.brief_job) ||
    isJobActive(run.voice?.speech_job) ||
    isJobActive(run.voice?.timing_job) ||
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

type ClickResult = {
  data?: GraphicRun;
  error?: unknown;
  response: Response;
};

function unwrapClick(result: ClickResult, failed: string): GraphicRun {
  if (!result.data) {
    throw new ApiError(
      detailMessage(result.error, `${failed} (HTTP ${result.response.status}).`),
      result.response.status,
    );
  }
  return result.data;
}

/**
 * The paid clicks of the director call (GFX-003). Each starts a model call and nothing else
 * runs it, so a button calls one of these only from a click. The runs are read again afterwards.
 */
function useBriefClick(send: (runId: number) => Promise<GraphicRun>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GRAPHICS_LAB_KEY }),
  });
}

/** Writes the brief of a run (one paid model call). */
export function useStartGraphicsBrief() {
  return useBriefClick(async (runId) =>
    unwrapClick(
      await api.POST("/api/lab/graphics/runs/{run_id}/brief", {
        params: { path: { run_id: runId } },
      }),
      "The brief was not started",
    ),
  );
}

/** Writes the brief, then starts every engine that is built. */
export function useMakeAllGraphics() {
  return useBriefClick(async (runId) =>
    unwrapClick(
      await api.POST("/api/lab/graphics/runs/{run_id}/make-all", {
        params: { path: { run_id: runId } },
      }),
      "Make all was not started",
    ),
  );
}

/** Makes a new run with the same line and writes its brief. The answer is the new run. */
export function useAskGraphicsAgain() {
  return useBriefClick(async (runId) =>
    unwrapClick(
      await api.POST("/api/lab/graphics/runs/{run_id}/ask-again", {
        params: { path: { run_id: runId } },
      }),
      "The new run was not made",
    ),
  );
}

export type GraphicTestCard = components["schemas"]["GraphicTestCardOut"];
export type GraphicTestCardResult = components["schemas"]["GraphicTestCardResultOut"];

const testCardKey = [...GRAPHICS_LAB_KEY, "test-card"] as const;

/**
 * The newest test card of the motion service: its job, and the newest video that was stored. It
 * is loaded again every few seconds while the job is waiting or running.
 */
export function useNewestGraphicsTestCard() {
  return useQuery({
    queryKey: testCardKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/lab/graphics/test-cards/newest");
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not load the test card (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/** Renders a test card in the motion service. It is free: no model is called. */
export function useRenderGraphicsTestCard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { orientation: GraphicOrientation; frames: number }) => {
      const { data, error, response } = await api.POST("/api/lab/graphics/test-cards", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The test card was not started (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: testCardKey }),
  });
}
