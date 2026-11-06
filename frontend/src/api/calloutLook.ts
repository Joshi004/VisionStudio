import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type CalloutLookState = components["schemas"]["CalloutLookState"];
export type CalloutLookOut = components["schemas"]["CalloutLookOut"];

/**
 * Every callout look query of a project starts with this key. It also starts with the project's
 * own key, so saving the project's settings (which refreshes the project) refreshes the card.
 */
export function calloutLookKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "callout-look"] as const;
}

async function fetchCalloutLook(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/callout-look", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the callout look (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the newest job and why it is out of date. It is loaded again every few
 * seconds while the job is waiting or running.
 */
export function useCalloutLook(projectId: number) {
  return useQuery({
    queryKey: calloutLookKey(projectId),
    queryFn: () => fetchCalloutLook(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/**
 * Starts the job that writes the look. `feedback` is the owner's note on the newest version;
 * leave it out for a plain run.
 */
export function useRunCalloutLook(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { feedback?: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/callout-look/run",
        {
          params: { path: { project_id: projectId } },
          body: { feedback: input.feedback ?? null },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the callout look (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: calloutLookKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
