import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type CalloutGraphicsState =
  components["schemas"]["CalloutGraphicsStateOut"];
export type CalloutGraphic = components["schemas"]["CalloutGraphicCalloutOut"];
export type CalloutGraphicEngine =
  components["schemas"]["CalloutGraphicEngineOut"];
export type CalloutGraphicAttempt =
  components["schemas"]["CalloutGraphicAttemptOut"];
export type CalloutGraphicEngineKey = CalloutGraphicEngine["key"];

/**
 * Every callout graphics query of a project starts with this key. It also starts with the
 * project's own key, so saving the project's settings (which refreshes the project) refreshes the
 * card.
 */
export function calloutGraphicsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "callout-graphics"] as const;
}

async function fetchCalloutGraphics(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/callout-graphics",
    {
      params: { path: { project_id: projectId } },
    },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the callout graphics (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/** Whether a version of the callout is being written or drawn. */
export function isCalloutGraphicWorking(callout: CalloutGraphic): boolean {
  return callout.status === "working";
}

/**
 * The callouts of the newest plan with the component of each. It is loaded again every few
 * seconds while any callout is being written or drawn.
 */
export function useCalloutGraphics(projectId: number) {
  return useQuery({
    queryKey: calloutGraphicsKey(projectId),
    queryFn: () => fetchCalloutGraphics(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.callouts.some(isCalloutGraphicWorking)
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** Makes what is missing for every callout that is turned on. */
export function useMakeCalloutGraphics(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/callout-graphics/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not make the callout graphics (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: calloutGraphicsKey(projectId),
        }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Makes what is missing for one callout, both versions or just `engine`. */
export function useMakeCalloutGraphic(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      calloutId: string;
      engine?: CalloutGraphicEngineKey;
    }) => {
      const params = {
        path: { project_id: projectId, callout_id: input.calloutId },
      };
      const { data, error, response } =
        input.engine === undefined
          ? await api.POST(
              "/api/projects/{project_id}/callout-graphics/{callout_id}/run",
              { params },
            )
          : await api.POST(
              "/api/projects/{project_id}/callout-graphics/{callout_id}/{engine}/run",
              {
                params: {
                  path: { ...params.path, engine: input.engine },
                },
              },
            );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not make the callout graphic (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: calloutGraphicsKey(projectId),
        }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** A paid model call: makes one version of one callout again as a new attempt. */
export function useAskCalloutGraphicAgain(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      calloutId: string;
      engine: CalloutGraphicEngineKey;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/callout-graphics/{callout_id}/{engine}/ask-again",
        {
          params: {
            path: {
              project_id: projectId,
              callout_id: input.calloutId,
              engine: input.engine,
            },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not ask again (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: calloutGraphicsKey(projectId),
        }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * The version the video uses for one callout. `null` is Automatic: the rule picks the generated
 * component, and the blocks only when the component failed outright.
 */
export function useSetCalloutGraphicChoice(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      calloutId: string;
      engine: CalloutGraphicEngineKey | null;
    }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/callout-graphics/{callout_id}/choice",
        {
          params: {
            path: { project_id: projectId, callout_id: input.calloutId },
          },
          body: { engine: input.engine },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not set the choice (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: calloutGraphicsKey(projectId),
      }),
  });
}
