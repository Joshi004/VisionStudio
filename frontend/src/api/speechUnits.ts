import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type SpeechUnits = components["schemas"]["SpeechUnitsOut"];
export type SpeechUnitsEntry = components["schemas"]["SpeechUnitsEntryOut"];
export type SpeechUnitsContent = components["schemas"]["SpeechUnitsContentOut"];
export type SpeechUnit = components["schemas"]["SpeechUnitOut"];
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
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: speechUnitsKey(projectId) }),
  });
}

/** Plans the speech units of one scene. */
export function usePlanOneSceneSpeechUnits(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/speech-units/{scene_id}/run",
        { params: { path: { project_id: projectId, scene_id: sceneId } } },
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
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: speechUnitsKey(projectId) }),
  });
}
