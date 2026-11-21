import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { evidenceKey } from "./evidence";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type EvidenceClaimsState = components["schemas"]["EvidenceClaimsState"];
export type EvidenceClaim = components["schemas"]["EvidenceClaimOut"];
export type EvidenceMarkInput = components["schemas"]["EvidenceMarkIn"];
export type EvidenceClaimEdit = components["schemas"]["EvidenceClaimEditIn"];
export type EvidenceKind = EvidenceClaim["kind_hint"];

/** The kinds a claim can have, in the order they are offered. */
export const EVIDENCE_KINDS: readonly { value: EvidenceKind; label: string }[] = [
  { value: "number", label: "Number" },
  { value: "quote", label: "Quote" },
  { value: "statement", label: "Statement" },
  { value: "event", label: "Event" },
  { value: "other", label: "Other" },
];

/**
 * Every evidence claims query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the claims,
 * which are re-anchored on every read.
 */
export function evidenceClaimsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "evidence-claims"] as const;
}

async function fetchEvidenceClaims(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/evidence-claims", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the claims (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The claims as they stand in the story, and the newest job. It is loaded again every few
 * seconds while the job is waiting or running.
 */
export function useEvidenceClaims(projectId: number, enabled = true) {
  return useQuery({
    queryKey: evidenceClaimsKey(projectId),
    queryFn: () => fetchEvidenceClaims(projectId),
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/** Marks words of the saved story as a claim. */
export function useMarkEvidenceClaim(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: EvidenceMarkInput) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/evidence-claims/marks",
        { params: { path: { project_id: projectId } }, body },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not mark the claim (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(evidenceClaimsKey(projectId), data);
      // The round of the evidence step may no longer have the claims that count.
      void queryClient.invalidateQueries({ queryKey: evidenceKey(projectId) });
    },
  });
}

/**
 * Changes a claim's note or kind, makes it a sound bite (`want` and `speaker`) or ordinary
 * evidence again, or keeps or drops a proposal of GLM.
 */
export function useEditEvidenceClaim(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { claimId: string; edit: EvidenceClaimEdit }) => {
      const { data, error, response } = await api.PATCH(
        "/api/projects/{project_id}/evidence-claims/{claim_id}",
        {
          params: { path: { project_id: projectId, claim_id: input.claimId } },
          body: input.edit,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the claim (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(evidenceClaimsKey(projectId), data);
      // The round of the evidence step may no longer have the claims that count.
      void queryClient.invalidateQueries({ queryKey: evidenceKey(projectId) });
    },
  });
}

/** Removes one of the owner's marks. */
export function useRemoveEvidenceClaim(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (claimId: string) => {
      const { data, error, response } = await api.DELETE(
        "/api/projects/{project_id}/evidence-claims/{claim_id}",
        { params: { path: { project_id: projectId, claim_id: claimId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not remove the claim (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(evidenceClaimsKey(projectId), data);
      // The round of the evidence step may no longer have the claims that count.
      void queryClient.invalidateQueries({ queryKey: evidenceKey(projectId) });
    },
  });
}

/** Starts the job that asks GLM for more claims (a paid call). */
export function useSuggestEvidenceClaims(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/evidence-claims/suggest",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not ask GLM for claims (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: evidenceClaimsKey(projectId) }),
        queryClient.invalidateQueries({ queryKey: evidenceKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
