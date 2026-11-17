import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type EvidenceState = components["schemas"]["EvidenceStateOut"];
export type EvidenceRound = components["schemas"]["EvidenceRoundOut"];
export type EvidenceImport = components["schemas"]["ImportOut"];
export type EvidenceImportClaim = components["schemas"]["ImportClaimOut"];

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
