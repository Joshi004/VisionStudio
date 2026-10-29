import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type SpeechAudio = components["schemas"]["SpeechAudioStateOut"];
export type SpeechSceneAudio = components["schemas"]["SpeechSceneAudioOut"];
export type SpeechUnitAudio = components["schemas"]["SpeechUnitAudioOut"];
export type SpeechTake = components["schemas"]["SpeechTakeOut"];
export type SpeechAudioRunAll = components["schemas"]["SpeechAudioRunAllOut"];

/**
 * Every speech-audio query of a project starts with this key (and the project's own), so saving
 * the story refreshes the "out of date" state too. Planning the units again changes it as well,
 * so `api/speechUnits.ts` refreshes it.
 */
export function speechAudioKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "speech-audio"] as const;
}

/** The measured length of a unit's audio, or of every unit that has some, in seconds. */
export function measuredSeconds(units: SpeechUnitAudio[]): number {
  return units.reduce(
    (sum, unit) => sum + (unit.audio?.measured_seconds ?? 0),
    0,
  );
}

async function fetchSpeechAudio(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/speech-audio",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the speech audio (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * Where the audio of every speech unit stands (and of every scene's take, for a continuous
 * explainer). It is loaded again every few seconds while any unit or take is being made, or a
 * unit's words are being timed.
 */
export function useSpeechAudio(projectId: number) {
  return useQuery({
    queryKey: speechAudioKey(projectId),
    queryFn: () => fetchSpeechAudio(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.scenes.some(
        (scene) =>
          scene.take?.status === "in_progress" ||
          scene.take?.word_timing?.status === "in_progress" ||
          scene.units.some(
            (unit) =>
              unit.status === "in_progress" ||
              unit.word_timing?.status === "in_progress",
          ),
      )
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** A refusal can mean something changed, so the state is loaded again either way. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: speechAudioKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Make all": starts the speech of every unit that has no current audio. */
export function useMakeAllSpeech(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/speech-audio/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the speech (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the speech of one unit (a fresh one, also after a failure or when it is made). */
export function useMakeOneSpeech(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; unitId: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/speech-audio/{scene_id}/{unit_id}/run",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: input.sceneId,
              unit_id: input.unitId,
            },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the speech (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the take of one scene of a continuous explainer (again, also after a failure). */
export function useMakeSceneTake(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/speech-audio/{scene_id}/take/run",
        {
          params: {
            path: { project_id: projectId, scene_id: input.sceneId },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the take (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}
