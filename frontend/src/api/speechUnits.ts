import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";
import { speechAudioKey } from "./speechAudio";

export type SpeechUnits = components["schemas"]["SpeechUnitsOut"];
export type SpeechUnitsEntry = components["schemas"]["SpeechUnitsEntryOut"];
export type SpeechUnitsContent = components["schemas"]["SpeechUnitsContentOut"];
export type SpeechUnit = components["schemas"]["SpeechUnitOut"];
export type SpeechUnitInput = components["schemas"]["SpeechUnitIn"];
export type SpeechPlanAll = components["schemas"]["SpeechUnitsRunAllOut"];

/** The total of the estimates of a plan, in seconds to a tenth. */
export function totalSeconds(units: SpeechUnitsContent): number {
  return (
    Math.round(
      units.units.reduce((sum, unit) => sum + unit.estimated_seconds, 0) * 10,
    ) / 10
  );
}

/**
 * Every speech-units query of a project starts with this key. It also starts with the project's
 * own key, so saving the story (which refreshes the project) refreshes the "out of date" state
 * too.
 */
export function speechUnitsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "speech-units"] as const;
}

/** A new plan changes which units have current audio, so the audio is loaded again too. */
function refreshAfterPlanning(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: speechUnitsKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: speechAudioKey(projectId) }),
  ]);
}

async function fetchSpeechUnits(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/speech-units",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the speech units (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of scenes with where each scene's speech units stand. Planning is done inside
 * the request, so nothing is polled.
 */
export function useSpeechUnits(projectId: number) {
  return useQuery({
    queryKey: speechUnitsKey(projectId),
    queryFn: () => fetchSpeechUnits(projectId),
    enabled: isValidProjectId(projectId),
  });
}

/** "Plan all": plans every scene that has current events and no current plan. */
export function usePlanAllSpeechUnits(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/speech-units/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not plan the speech units (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean something changed, so the state is loaded again either way.
    onSettled: () => refreshAfterPlanning(queryClient, projectId),
  });
}

/**
 * Plans the speech units of one scene. `confirmReplaceManual` is true only after the user agreed
 * to replace cuts they made.
 */
export function usePlanOneSceneSpeechUnits(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/speech-units/{scene_id}/run",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not plan the speech units (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterPlanning(queryClient, projectId),
  });
}

/** Saves one scene's re-split speech units as its next plan, written by the user. */
export function useSaveSpeechUnits(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; units: SpeechUnitInput[] }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/speech-units/{scene_id}",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: { units: input.units },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the speech units (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // A new plan changes which units have current audio, so the audio is loaded again too.
    onSuccess: () =>
      Promise.all([
        refreshProject(queryClient, projectId),
        refreshAfterPlanning(queryClient, projectId),
      ]),
  });
}
