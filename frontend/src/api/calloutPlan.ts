import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";

export type CalloutPlanState = components["schemas"]["CalloutPlanState"];
export type CalloutPlanOut = components["schemas"]["CalloutPlanOut"];
export type CalloutPlanVersion = components["schemas"]["CalloutPlanVersionOut"];
export type CalloutPlanInput = components["schemas"]["CalloutPlanSaveIn"];
export type Callout = components["schemas"]["CalloutOut"];
export type CalloutEdit = components["schemas"]["CalloutEditIn"];
export type CalloutType = Callout["type"];
export type CalloutRole = NonNullable<Callout["role"]>;
export type CalloutScriptLine = components["schemas"]["CalloutScriptLineOut"];

/**
 * Every callout plan query of a project starts with this key. It also starts with the project's
 * own key, so saving the project's settings (which refreshes the project) refreshes the panel.
 */
export function calloutPlanKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "callout-plan"] as const;
}

async function fetchCalloutPlan(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/callout-plan", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the callout plan (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the list of versions, the newest job, why it is out of date, the limits and
 * the script the callouts sit on. It is loaded again every few seconds while the job is waiting
 * or running.
 */
export function useCalloutPlan(projectId: number) {
  return useQuery({
    queryKey: calloutPlanKey(projectId),
    queryFn: () => fetchCalloutPlan(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

async function fetchCalloutPlanVersion(projectId: number, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/callout-plan/versions/{version}",
    { params: { path: { project_id: projectId, version } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the version (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** One stored version. Nothing is loaded while `version` is null. */
export function useCalloutPlanVersion(projectId: number, version: number | null) {
  return useQuery({
    queryKey: [...calloutPlanKey(projectId), "version", version],
    queryFn: () => fetchCalloutPlanVersion(projectId, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/**
 * Starts the job that writes the plan. `confirmReplaceManual` is true only after the owner
 * agreed to add a version from the model on top of one they wrote.
 */
export function useRunCalloutPlan(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/callout-plan/run",
        {
          params: { path: { project_id: projectId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the callout plan (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: calloutPlanKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Saves the edited callouts as the next version, written by the owner. */
export function useSaveCalloutPlan(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (content: CalloutPlanInput) => {
      const { data, error, response } = await api.PUT("/api/projects/{project_id}/callout-plan", {
        params: { path: { project_id: projectId } },
        body: content,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the callout plan (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
