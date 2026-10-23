import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { ENVIRONMENT_LAB_KEY } from "./environmentLab";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type EnvironmentViewsState = components["schemas"]["EnvironmentViewsOut"];
export type EnvironmentViewsEntry = components["schemas"]["EnvironmentViewsEntryOut"];
export type EnvironmentView = components["schemas"]["ViewOut"];

/** Every environment-views query of a project starts with this key. */
export function environmentViewsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "environment-views"] as const;
}

const labViewsKey = (environmentId: number | null) =>
  [...ENVIRONMENT_LAB_KEY, "views", environmentId] as const;

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

/** Is a view's picture still being written or drawn? */
export function viewIsBusy(view: EnvironmentView): boolean {
  return view.status === "in_progress";
}

/** An environment is busy while its plan is being made or any of its views is. */
export function entryIsBusy(entry: EnvironmentViewsEntry): boolean {
  return isJobActive(entry.job) || entry.views.some(viewIsBusy);
}

// --- A project's views ---------------------------------------------------------------------

async function fetchViews(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/environment-views",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw failure(error, response.status, "Could not load the environment views");
  }
  return data;
}

/**
 * The environments scenes are set in, each with its view plan and views. It is loaded again every
 * few seconds while a plan is being made or a picture is being drawn.
 */
export function useEnvironmentViews(projectId: number) {
  return useQuery({
    queryKey: environmentViewsKey(projectId),
    queryFn: () => fetchViews(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some(entryIsBusy) ? ACTIVE_POLL_MS : false,
  });
}

/** A change can touch the project's views, the library, and the jobs. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: environmentViewsKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: ENVIRONMENT_LAB_KEY }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Plan all": plans every environment whose plan is missing or out of date. */
export function usePlanAllEnvironmentViews(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-views/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not start the view planning");
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

export function usePlanEnvironmentViews(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-views/{discovery_id}/run",
        { params: { path: { project_id: projectId, discovery_id: discoveryId } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not start the view planning");
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the pictures of every view of one environment's plan that has none. */
export function useMakeViewPictures(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (discoveryId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-views/{discovery_id}/pictures",
        { params: { path: { project_id: projectId, discovery_id: discoveryId } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not start the pictures");
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Makes one view's picture again from the master picture the project pins. */
export function useRemakeProjectView(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (viewId: number) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/environment-views/views/{view_id}/remake",
        { params: { path: { project_id: projectId, view_id: viewId } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not start the picture");
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

// --- The lab's views -----------------------------------------------------------------------

async function fetchLabViews(environmentId: number) {
  const { data, error, response } = await api.GET(
    "/api/lab/environments/{environment_id}/views",
    { params: { path: { environment_id: environmentId } } },
  );
  if (!data) {
    throw failure(error, response.status, "Could not load the views");
  }
  return data;
}

/**
 * The views of a library environment. A story project's plan creates them. They are loaded again
 * every few seconds while a picture is being made.
 */
export function useLabEnvironmentViews(environmentId: number | null) {
  return useQuery({
    queryKey: labViewsKey(environmentId),
    queryFn: () => fetchLabViews(environmentId as number),
    enabled: environmentId !== null,
    refetchInterval: (current) =>
      current.state.data?.some(viewIsBusy) ? ACTIVE_POLL_MS : false,
  });
}

/** Makes one view's picture again from the environment's newest master picture. */
export function useRemakeLabView(environmentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (viewId: number) => {
      const { data, error, response } = await api.POST(
        "/api/lab/environments/{environment_id}/views/{view_id}/remake",
        { params: { path: { environment_id: environmentId, view_id: viewId } } },
      );
      if (!data) {
        throw failure(error, response.status, "Could not start the picture");
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ENVIRONMENT_LAB_KEY }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
