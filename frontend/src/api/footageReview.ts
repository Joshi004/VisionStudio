import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { footageKey } from "./footage";
import { footageFilesKey } from "./footageFiles";
import { invalidateAfterJobAction } from "./jobs";
import { pipelineBoardKey } from "./pipelineBoard";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId } from "./projects";
import type { components } from "./schema";

export type FootageReview = components["schemas"]["FootageReviewOut"];
export type FootageReviewMark = components["schemas"]["FootageReviewMarkOut"];
export type FootageReviewPiece = components["schemas"]["FootageReviewPieceOut"];
export type FootageFraming = NonNullable<FootageReviewMark["framing"]>;

/** An agent's video can play for 2 to 15 seconds (the brief's `clip_seconds`). */
export const FOOTAGE_REVIEW_USE_MIN_S = 2;
export const FOOTAGE_REVIEW_USE_MAX_S = 15;
/** The start and end move by this many seconds with the nudge buttons. */
export const FOOTAGE_REVIEW_STEP_S = 0.5;

/**
 * The review query of a project. It sits under the footage query's key, so whatever refreshes the
 * footage research refreshes the review too.
 */
export function footageReviewKey(projectId: number) {
  return [...footageKey(projectId), "review"] as const;
}

async function fetchReview(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/footage/review", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the footage review (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The pieces the research found, for the owner to decide on. Loaded again every few seconds
 * while a preview is being drawn. */
export function useFootageReview(projectId: number, enabled = true) {
  return useQuery({
    queryKey: footageReviewKey(projectId),
    queryFn: () => fetchReview(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.marks.some((mark) =>
        [...mark.pieces, ...mark.shown].some((piece) => isJobActive(piece.preview)),
      )
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** After a decision: the review is replaced by the answer, and whatever reads the same decisions
 * (the research panel, the owner's files, the pipeline board) is loaded again. */
function useAfterDecision(projectId: number) {
  const queryClient = useQueryClient();
  return (data?: FootageReview) => {
    if (data !== undefined) {
      queryClient.setQueryData(footageReviewKey(projectId), data);
    }
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: footageKey(projectId) }),
      queryClient.invalidateQueries({ queryKey: footageFilesKey(projectId) }),
      queryClient.invalidateQueries({ queryKey: pipelineBoardKey(projectId) }),
    ]);
  };
}

/** Accepts or rejects a piece of the agent. */
export function useDecideFootagePiece(projectId: number) {
  const afterDecision = useAfterDecision(projectId);
  return useMutation({
    mutationFn: async (input: { itemKey: string; verdict: "accepted" | "rejected" }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/footage/review/items/{item_key}",
        {
          params: { path: { project_id: projectId, item_key: input.itemKey } },
          body: { verdict: input.verdict },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the choice (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterDecision,
  });
}

/** Moves where an agent's video starts and ends, in seconds of the stored video. */
export function useSetFootageReviewUse(projectId: number) {
  const afterDecision = useAfterDecision(projectId);
  return useMutation({
    mutationFn: async (input: { itemKey: string; startS: number; endS: number }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/footage/review/items/{item_key}/use",
        {
          params: { path: { project_id: projectId, item_key: input.itemKey } },
          body: { start_s: input.startS, end_s: input.endS },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not move the start and end (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterDecision,
  });
}

/** Sets the portrait crop of a mark (null fits the picture over a blurred copy). */
export function useSetFootageFraming(projectId: number) {
  const afterDecision = useAfterDecision(projectId);
  return useMutation({
    mutationFn: async (input: { markId: string; framing: FootageFraming | null }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/footage/review/marks/{mark_id}/framing",
        {
          params: { path: { project_id: projectId, mark_id: input.markId } },
          body: { framing: input.framing },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the crop (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterDecision,
  });
}

/** Sets or clears "no footage here" on a mark. */
export function useSetFootageReviewNoFootage(projectId: number) {
  const afterDecision = useAfterDecision(projectId);
  return useMutation({
    mutationFn: async (input: { markId: string; noFootage: boolean }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/footage/review/marks/{mark_id}/no-footage",
        {
          params: { path: { project_id: projectId, mark_id: input.markId } },
          body: { no_footage: input.noFootage },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the choice (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterDecision,
  });
}

/** Puts the pieces shown on a mark in a new order. */
export function useReorderFootageShown(projectId: number) {
  const afterDecision = useAfterDecision(projectId);
  return useMutation({
    mutationFn: async (input: { markId: string; shown: string[] }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/footage-marks/{mark_id}/order",
        {
          params: { path: { project_id: projectId, mark_id: input.markId } },
          body: { shown: input.shown },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the order (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => afterDecision(),
  });
}

/** Takes one of the owner's own files off its mark. */
export function useRemoveOwnFootageFile(projectId: number) {
  const afterDecision = useAfterDecision(projectId);
  return useMutation({
    mutationFn: async (itemKey: string) => {
      const { data, error, response } = await api.DELETE(
        "/api/projects/{project_id}/footage-files/{item_key}",
        { params: { path: { project_id: projectId, item_key: itemKey } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not remove the file (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => afterDecision(),
  });
}

/** Starts the job that draws a 6 second preview of a piece as it will be over the shots. */
export function useStartFootageReviewPreview(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (itemKey: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/footage-files/{item_key}/preview",
        { params: { path: { project_id: projectId, item_key: itemKey } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the preview (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: footageReviewKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Marks the newest round reviewed. */
export function useFinishFootageReview(projectId: number) {
  const afterDecision = useAfterDecision(projectId);
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/footage/review/done",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not finish the review (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterDecision,
  });
}
