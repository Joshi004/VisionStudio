import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type MusicTakesState = components["schemas"]["MusicTakesState"];
export type MusicTakeItem = components["schemas"]["MusicTakeItemOut"];
export type MusicTake = components["schemas"]["MusicTakeOut"];
export type MusicTakeCheck = components["schemas"]["TakeCheckOut"];

/**
 * Every music takes query of a project starts with this key. It also starts with the project's
 * own key, so a change to the project refreshes the panel.
 */
export function musicTakesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "music-takes"] as const;
}

async function fetchMusicTakes(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/music-takes",
    {
      params: { path: { project_id: projectId } },
    },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the music takes (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The takes of every cue and hit of the newest plan. It is loaded again every few seconds while
 * a take is being made or checked, or a prompt is being rewritten.
 */
export function useMusicTakes(projectId: number) {
  return useQuery({
    queryKey: musicTakesKey(projectId),
    queryFn: () => fetchMusicTakes(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.active)
        ? ACTIVE_POLL_MS
        : false,
  });
}

function useRefreshAfter(projectId: number) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: musicTakesKey(projectId) }),
      invalidateAfterJobAction(queryClient),
    ]);
}

/**
 * Makes the takes of every item that needs them, or of one item (`itemId`).
 * `confirmReplaceOwner` is true only after the owner agreed to replace a take they chose.
 */
export function useRunMusicTakes(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: {
      itemId?: string;
      confirmReplaceOwner: boolean;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-takes/run",
        {
          params: {
            path: { project_id: projectId },
            query: input.itemId === undefined ? {} : { item_id: input.itemId },
          },
          body: { confirm_replace_owner: input.confirmReplaceOwner },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the takes (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: refresh,
  });
}

/** Selects a take, also one that failed its check. */
export function useSelectMusicTake(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (takeId: number) => {
      const { error, response } = await api.POST(
        "/api/projects/{project_id}/music-takes/{take_id}/select",
        { params: { path: { project_id: projectId, take_id: takeId } } },
      );
      // The answer has no body (204), so success is the status and not `data`.
      if (!response.ok) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not select the take (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
    },
    onSuccess: refresh,
  });
}

/** Rejects a take with a note: the model rewrites its prompt and a new take is made. */
export function useRejectMusicTake(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { takeId: number; note: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-takes/{take_id}/reject",
        {
          params: { path: { project_id: projectId, take_id: input.takeId } },
          body: { note: input.note },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not reject the take (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: refresh,
  });
}

/** Locks the selected take, or removes the lock. */
export function useLockMusicTake(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { takeId: number; locked: boolean }) => {
      const params = { path: { project_id: projectId, take_id: input.takeId } };
      const path = "/api/projects/{project_id}/music-takes/{take_id}/lock";
      const { error, response } = input.locked
        ? await api.POST(path, { params })
        : await api.DELETE(path, { params });
      if (!response.ok) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not change the lock (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
    },
    onSuccess: refresh,
  });
}
