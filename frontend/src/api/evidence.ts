import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { pipelineBoardKey } from "./pipelineBoard";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type EvidenceState = components["schemas"]["EvidenceStateOut"];
export type EvidenceRound = components["schemas"]["EvidenceRoundOut"];
export type EvidenceImport = components["schemas"]["ImportOut"];
export type EvidenceImportClaim = components["schemas"]["ImportClaimOut"];
export type EvidenceReview = components["schemas"]["EvidenceReviewOut"];
export type EvidenceReviewClaim = components["schemas"]["ReviewClaimOut"];
export type EvidenceReviewItem = components["schemas"]["ReviewItemOut"];
export type EvidenceClaimDecision = components["schemas"]["ClaimDecisionIn"];
export type EvidencePreview = components["schemas"]["PreviewOut"];

/**
 * The evidence query of a project. It sits under the project's own key, so whatever refreshes
 * the project refreshes it, and changing a claim refreshes it too (`api/evidenceClaims.ts`).
 */
export function evidenceKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "evidence"] as const;
}

async function fetchEvidence(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/evidence", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the evidence (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * Where the project's evidence stands. Loaded again every few seconds while the brief is written
 * or the results are imported.
 */
export function useEvidence(projectId: number, enabled = true) {
  return useQuery({
    queryKey: evidenceKey(projectId),
    queryFn: () => fetchEvidence(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (query) =>
      isJobActive(query.state.data?.job) || isJobActive(query.state.data?.import_job)
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** Starts the job that writes the next round's brief into the files folder. */
export function useWriteEvidenceBrief(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/evidence/brief",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not write the brief (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: evidenceKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Starts the job that checks the newest round's results and copies the usable files in. */
export function useImportEvidence(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/evidence/import",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not import the evidence (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: evidenceKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** The owner's review sits under the evidence key, so refreshing the evidence refreshes it. */
export function evidenceReviewKey(projectId: number) {
  return [...evidenceKey(projectId), "review"] as const;
}

async function fetchEvidenceReview(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/evidence/review", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the review (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest import, claim by claim, with the owner's decisions. Loaded again every few seconds
 * while a preview video is being drawn.
 */
export function useEvidenceReview(projectId: number, enabled = true) {
  return useQuery({
    queryKey: evidenceReviewKey(projectId),
    queryFn: () => fetchEvidenceReview(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.claims.some((claim) =>
        claim.items.some(
          (item) =>
            isJobActive(item.preview) || item.soundbite?.transcription.status === "in_progress",
        ),
      )
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** Starts the job that draws a short preview video of one accepted piece of evidence. */
export function useStartEvidencePreview(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (itemKey: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/evidence/review/items/{item_key}/preview",
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
        queryClient.invalidateQueries({ queryKey: evidenceReviewKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Queues the transcription of a sound bite clip again, after it failed. */
export function useTranscribeEvidenceClip(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (itemKey: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/evidence/review/items/{item_key}/transcribe",
        { params: { path: { project_id: projectId, item_key: itemKey } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the transcription (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: evidenceReviewKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** A decision changes whether the `evidence` step is done, so the board is refreshed too. */
function useAfterReviewChange(projectId: number) {
  const queryClient = useQueryClient();
  return (data: EvidenceReview) => {
    queryClient.setQueryData(evidenceReviewKey(projectId), data);
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: evidenceKey(projectId), exact: true }),
      queryClient.invalidateQueries({ queryKey: pipelineBoardKey(projectId) }),
    ]);
  };
}

/** Replaces the owner's decision on one claim. */
export function useSaveEvidenceClaimDecision(projectId: number) {
  const afterChange = useAfterReviewChange(projectId);
  return useMutation({
    mutationFn: async (input: { claimId: string; decision: EvidenceClaimDecision }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/evidence/review/claims/{claim_id}",
        {
          params: { path: { project_id: projectId, claim_id: input.claimId } },
          body: input.decision,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the decision (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: afterChange,
  });
}

/** "Review done": ends the review once every claim is decided. */
export function useFinishEvidenceReview(projectId: number) {
  const afterChange = useAfterReviewChange(projectId);
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/evidence/review/done",
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
    onSuccess: afterChange,
  });
}
