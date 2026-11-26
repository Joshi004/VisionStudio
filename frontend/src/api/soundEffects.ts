import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type SoundEffectsState = components["schemas"]["SoundEffectsState"];
export type SoundEffect = components["schemas"]["SoundEffectOut"];
export type SoundEffectTake = components["schemas"]["SoundEffectTakeOut"];
export type SoundEffectRole = SoundEffect["role"];

/**
 * Every sound effects query of a project starts with this key. It also starts with the project's
 * own key, so a change to the project (the switch) refreshes the panel.
 */
export function soundEffectsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "sound-effects"] as const;
}

async function fetchSoundEffects(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/sound-effects",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the sound effects (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The project's sounds and their takes. It is loaded again every few seconds while a prompt is
 * being written or a take is being made or checked.
 */
export function useSoundEffects(projectId: number) {
  return useQuery({
    queryKey: soundEffectsKey(projectId),
    queryFn: () => fetchSoundEffects(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.sounds.some((sound) => sound.active)
        ? ACTIVE_POLL_MS
        : false,
  });
}

function useRefreshAfter(projectId: number) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: soundEffectsKey(projectId) }),
      invalidateAfterJobAction(queryClient),
    ]);
}

/** Makes the sounds that have no takes, or a new round of one sound (`role`). */
export function useRunSoundEffects(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { role?: SoundEffectRole }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/sound-effects/run",
        {
          params: {
            path: { project_id: projectId },
            query: input.role === undefined ? {} : { role: input.role },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the sound effects (HTTP ${response.status}).`,
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
export function useSelectSoundEffectTake(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (takeId: number) => {
      const { error, response } = await api.POST(
        "/api/projects/{project_id}/sound-effects/{take_id}/select",
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

/** Rejects a take with a note: the model rewrites the prompt and new takes are made. */
export function useRejectSoundEffectTake(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { takeId: number; note: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/sound-effects/{take_id}/reject",
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
export function useLockSoundEffectTake(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { takeId: number; locked: boolean }) => {
      const params = { path: { project_id: projectId, take_id: input.takeId } };
      const path = "/api/projects/{project_id}/sound-effects/{take_id}/lock";
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
