import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";
import { storyBibleKey } from "./storyBible";

export type DiscoveryKind = "characters" | "environments";
export type DiscoveryState = components["schemas"]["DiscoveryState"];
export type DiscoveryOut = components["schemas"]["DiscoveryOut"];
export type DiscoveryVersion = components["schemas"]["DiscoveryVersionOut"];
export type DiscoveryItemInput = components["schemas"]["DiscoveryItemIn"];
export type DiscoveryItem = components["schemas"]["DiscoveryItem"];

/**
 * Every discovery query of a project and kind starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" flag.
 */
function discoveryKey(projectId: number, kind: DiscoveryKind) {
  return [...PROJECTS_KEY, projectId, "discovery", kind] as const;
}

async function fetchDiscovery(projectId: number, kind: DiscoveryKind) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/discovery/{kind}", {
    params: { path: { project_id: projectId, kind } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the ${kind} (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the list of versions, the newest job and the "out of date" flag. It is
 * loaded again every few seconds while the job is waiting or running.
 */
export function useDiscovery(projectId: number, kind: DiscoveryKind) {
  return useQuery({
    queryKey: discoveryKey(projectId, kind),
    queryFn: () => fetchDiscovery(projectId, kind),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

async function fetchDiscoveryVersion(projectId: number, kind: DiscoveryKind, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/discovery/{kind}/versions/{version}",
    { params: { path: { project_id: projectId, kind, version } } },
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
export function useDiscoveryVersion(
  projectId: number,
  kind: DiscoveryKind,
  version: number | null,
) {
  return useQuery({
    queryKey: [...discoveryKey(projectId, kind), "version", version],
    queryFn: () => fetchDiscoveryVersion(projectId, kind, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/**
 * Starts the job that finds the next version from the saved story. `confirmReplaceManual` is true
 * only after the user agreed to add a version from the model on top of a list they wrote.
 */
export function useRunDiscovery(projectId: number, kind: DiscoveryKind) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/discovery/{kind}/run",
        {
          params: { path: { project_id: projectId, kind } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the ${kind} search (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean the Story Bible is missing or out of date, so its state is loaded
    // again too, whether the run started or not.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: discoveryKey(projectId, kind) }),
        queryClient.invalidateQueries({ queryKey: storyBibleKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Saves the whole edited list as the next version, written by the user. */
export function useSaveDiscovery(projectId: number, kind: DiscoveryKind) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (items: DiscoveryItemInput[]) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/discovery/{kind}",
        { params: { path: { project_id: projectId, kind } }, body: { items } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the ${kind} (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
