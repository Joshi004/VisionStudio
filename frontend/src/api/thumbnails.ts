import { useRef } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type ThumbnailsState = components["schemas"]["ThumbnailsState"];
export type ThumbnailIdeas = components["schemas"]["IdeasState"];
export type ThumbnailConcept = components["schemas"]["ConceptOut"];
export type ThumbnailConceptInput = components["schemas"]["ConceptIn"];
export type ThumbnailPerson = components["schemas"]["PersonOut"];
export type ThumbnailCastOption = components["schemas"]["CastOptionOut"];
export type Thumbnail = components["schemas"]["ThumbnailOut"];
export type ThumbnailTextArea = ThumbnailConcept["text_area"];

/** Every thumbnail query of a project starts with this key, so refreshing the project refreshes it. */
export function thumbnailsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "thumbnails"] as const;
}

/**
 * Every Publish panel query of a project starts with this key, whatever render it shows. It is
 * defined here, and not in `youtube.ts`, because a change to a thumbnail also refreshes the
 * Publish panel (its chosen thumbnail and whether Upload is possible), and `youtube.ts` already
 * imports this file.
 */
export function youtubePanelKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "youtube"] as const;
}

async function fetchThumbnails(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/thumbnails",
    {
      params: { path: { project_id: projectId } },
    },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the thumbnails (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/** Extra loads after the last busy one: the pictures start a moment after their ideas are stored. */
const GRACE_POLLS = 2;

/**
 * The thumbnail ideas, the pictures made from them and why either is out of date. It is loaded
 * again every few seconds while the ideas are being written or a picture is being made, and
 * twice more after that, because the pictures of new ideas are started just after the ideas are
 * stored and nothing is "busy" in between.
 */
export function useThumbnails(projectId: number) {
  const gracePolls = useRef(0);
  return useQuery({
    queryKey: thumbnailsKey(projectId),
    queryFn: () => fetchThumbnails(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => {
      const state = query.state.data;
      const busy =
        isJobActive(state?.ideas.job) ||
        (state?.thumbnails.some((thumbnail) => isJobActive(thumbnail.job)) ??
          false);
      if (busy) {
        gracePolls.current = GRACE_POLLS;
        return ACTIVE_POLL_MS;
      }
      if (gracePolls.current > 0) {
        gracePolls.current -= 1;
        return ACTIVE_POLL_MS;
      }
      return false;
    },
  });
}

/**
 * What the mutations that return the whole state do: show it at once, and refresh the job list
 * and the Publish panel (its chosen thumbnail and whether Upload is possible).
 */
function showState(
  queryClient: QueryClient,
  projectId: number,
  state: ThumbnailsState,
) {
  queryClient.setQueryData(thumbnailsKey(projectId), state);
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: youtubePanelKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** Starts the job that writes four ideas. `feedback` is a note for the model, or null. */
export function useRunThumbnailIdeas(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { feedback: string | null }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/thumbnail-concepts/run",
        {
          params: { path: { project_id: projectId } },
          body: { feedback: input.feedback },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the thumbnail ideas (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: thumbnailsKey(projectId) }),
        queryClient.invalidateQueries({ queryKey: youtubePanelKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Saves the edited ideas as the next version, written by the owner. */
export function useSaveThumbnailIdeas(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (concepts: ThumbnailConceptInput[]) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/thumbnail-concepts",
        { params: { path: { project_id: projectId } }, body: { concepts } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not save the ideas (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (state) => showState(queryClient, projectId, state),
  });
}

/** Makes one picture for each of the chosen ideas of one version. */
export function useMakeThumbnails(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      conceptVersion: number;
      indexes: number[];
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/thumbnails",
        {
          params: { path: { project_id: projectId } },
          body: {
            concept_version: input.conceptVersion,
            indexes: input.indexes,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the pictures (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (state) => showState(queryClient, projectId, state),
  });
}

/** Changes the headline of one thumbnail. The text is drawn on the picture again. */
export function useSetThumbnailHeadline(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { thumbnailId: number; headline: string }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/thumbnails/{thumbnail_id}/headline",
        {
          params: {
            path: { project_id: projectId, thumbnail_id: input.thumbnailId },
          },
          body: { headline: input.headline },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not change the headline (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (state) => showState(queryClient, projectId, state),
  });
}

/** Marks one thumbnail as the chosen one, or takes the mark off. */
export function useChooseThumbnail(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { thumbnailId: number; chosen: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/thumbnails/{thumbnail_id}/choose",
        {
          params: {
            path: { project_id: projectId, thumbnail_id: input.thumbnailId },
          },
          body: { chosen: input.chosen },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not choose the thumbnail (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (state) => showState(queryClient, projectId, state),
  });
}
