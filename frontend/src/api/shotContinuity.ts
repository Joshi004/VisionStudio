import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId } from "./projects";
import type { components } from "./schema";
import { shotDefinitionsKey } from "./shotDefinitions";

export type ShotContinuity = components["schemas"]["ShotContinuityOut"];
export type SceneContinuity = components["schemas"]["SceneContinuityOut"];
export type ShotContinuityFlag = components["schemas"]["ShotContinuityFlagOut"];
/** A cut between two shots (or at a scene's start or end) that does not line up. */
export type ContinuityMismatch = components["schemas"]["ContinuityMismatchOut"];
export type ShotContinuityRun =
  components["schemas"]["ShotContinuityRunManyOut"];

/**
 * How long the continuity state keeps asking after something last ran. A scene's check is
 * queued a moment after its last shot is defined, and the cuts that do not line up are queued
 * for repair a moment after a check finishes, so the page must not stop asking the instant
 * nothing runs.
 */
const GRACE_MS = 15_000;

/**
 * The continuity query of a project. It starts with the shot definitions' key, so whatever
 * refreshes the shot definitions (pressing Define, saving the story) refreshes this too: a
 * scene's continuity is worked out from its shots' definitions.
 */
export function shotContinuityKey(projectId: number) {
  return [...shotDefinitionsKey(projectId), "continuity"] as const;
}

async function fetchShotContinuity(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/shot-continuity",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the shot continuity (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/** Whether a scene's check or the repairs of its cuts are waiting or running. */
export function isContinuityBusy(scene: SceneContinuity): boolean {
  return (
    scene.status === "checking" ||
    scene.status === "reconciling" ||
    isJobActive(scene.job)
  );
}

/**
 * Where each scene's continuity stands. It is loaded again every few seconds while a check or a
 * cut repair runs, while shots are being defined (a check follows the last one), and for a
 * short while after either.
 */
export function useShotContinuity(
  projectId: number,
  definitionsActive: boolean,
) {
  const queryClient = useQueryClient();
  const lastActive = useRef(0);
  return useQuery({
    queryKey: shotContinuityKey(projectId),
    queryFn: async () => {
      const data = await fetchShotContinuity(projectId);
      if (data.entries.some(isContinuityBusy)) {
        // A cut repair writes new shot definitions: the shots' own list must follow it. Only
        // that list (`exact`), or the two would refresh each other without end.
        void queryClient.invalidateQueries({
          queryKey: shotDefinitionsKey(projectId),
          exact: true,
        });
      }
      return data;
    },
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) => {
      const busy = current.state.data?.entries.some(isContinuityBusy) ?? false;
      if (busy || definitionsActive) {
        lastActive.current = Date.now();
        return ACTIVE_POLL_MS;
      }
      return Date.now() - lastActive.current < GRACE_MS
        ? ACTIVE_POLL_MS
        : false;
    },
  });
}

/** A refusal can mean something changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: shotDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

function startError(error: unknown, status: number): ApiError {
  return new ApiError(
    detailMessage(
      error,
      `Could not start the continuity check (HTTP ${status}).`,
    ),
    status,
  );
}

/** "Check all continuity": checks every scene whose shots are all defined and not consistent yet. */
export function useCheckAllContinuity(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-continuity/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw startError(error, response.status);
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Checks the continuity of one scene. */
export function useCheckSceneContinuity(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-continuity/{scene_id}/run",
        { params: { path: { project_id: projectId, scene_id: sceneId } } },
      );
      if (!data) {
        throw startError(error, response.status);
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * "Fix this cut": repairs one cut that the newest check found not lining up. One call sees both
 * shots and decides which side changes; the automatic rounds follow it.
 */
export function useRepairCut(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      sceneId,
      boundaryId,
      confirmReplaceManual,
    }: {
      sceneId: string;
      boundaryId: string;
      /** True only after the user agreed to change shots they wrote. */
      confirmReplaceManual: boolean;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-continuity/{scene_id}/cuts/{boundary_id}/repair",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: sceneId,
              boundary_id: boundaryId,
            },
          },
          body: { confirm_replace_manual: confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the repair of the cut (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}
