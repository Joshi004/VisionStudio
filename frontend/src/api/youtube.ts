import { useRef } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";
import { thumbnailsKey } from "./thumbnails";

export type YouTubeConfig = components["schemas"]["YouTubeConfig"];
export type YouTubeChannel = components["schemas"]["YouTubeChannelOut"];
export type YouTubePanel = components["schemas"]["YouTubePanelOut"];
export type YouTubeDraft = components["schemas"]["YouTubeDraftOut"];
export type YouTubeRender = components["schemas"]["YouTubeRenderOut"];
export type YouTubeThumbnail = components["schemas"]["YouTubeThumbnailOut"];
export type YouTubeUpload = components["schemas"]["YouTubeUploadOut"];
export type YouTubePrivacy = YouTubePanel["default_privacy"];

const CONFIG_KEY = ["youtube", "config"] as const;
const CHANNELS_KEY = ["youtube", "channels"] as const;

export function useYouTubeConfig() {
  return useQuery({
    queryKey: CONFIG_KEY,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/youtube/config");
      if (!data) {
        throw new ApiError(
          `Could not check the YouTube setup (HTTP ${response.status}).`,
          response.status,
        );
      }
      return data;
    },
  });
}

export function useYouTubeChannels() {
  return useQuery({
    queryKey: CHANNELS_KEY,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/youtube/channels");
      if (!data) {
        throw new ApiError(
          `Could not load the YouTube channels (HTTP ${response.status}).`,
          response.status,
        );
      }
      return data;
    },
  });
}

/** Asks for Google's sign-in address, then sends the browser there. It comes back to Settings. */
export function useStartYouTubeSignIn() {
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/youtube/oauth/start",
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the sign-in (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data.url;
    },
    onSuccess: (url) => {
      window.location.assign(url);
    },
  });
}

/** Uses the channel's token once. A refused token turns the channel to "needs reconnect". */
export function useCheckYouTubeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (channelRowId: number) => {
      const { data, error, response } = await api.POST(
        "/api/youtube/channels/{channel_row_id}/check",
        { params: { path: { channel_row_id: channelRowId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not check the channel (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: CHANNELS_KEY }),
  });
}

export function useDisconnectYouTubeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (channelRowId: number) => {
      const { data, error, response } = await api.DELETE(
        "/api/youtube/channels/{channel_row_id}",
        { params: { path: { channel_row_id: channelRowId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not disconnect the channel (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_KEY }),
  });
}

// --- The publish draft of a project --------------------------------------------------------

/** Every Publish panel query of a project starts with this key, whatever render it shows. */
export function youtubePanelKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "youtube"] as const;
}

function youtubePanelRenderKey(projectId: number, renderNumber: number | null) {
  return [...youtubePanelKey(projectId), renderNumber] as const;
}

async function fetchPanel(projectId: number, renderNumber: number | null) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/youtube",
    {
      params: {
        path: { project_id: projectId },
        query: renderNumber === null ? {} : { render_number: renderNumber },
      },
    },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the YouTube draft (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/** Extra loads after the last busy one: the thumbnail's picture starts a moment after its ideas end. */
const GRACE_POLLS = 2;

/**
 * What the Publish panel shows for one render (the newest when `renderNumber` is null). It is
 * loaded again every few seconds while the draft is being written or a thumbnail is being made,
 * and twice more after that, because the picture of a new thumbnail is started just after its
 * ideas are stored and nothing is "making" in between.
 */
export function useYouTubePanel(
  projectId: number,
  renderNumber: number | null,
) {
  const gracePolls = useRef(0);
  return useQuery({
    queryKey: youtubePanelRenderKey(projectId, renderNumber),
    queryFn: () => fetchPanel(projectId, renderNumber),
    enabled: isValidProjectId(projectId),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const state = query.state.data;
      const busy =
        isJobActive(state?.job) ||
        state?.thumbnail.status === "making" ||
        (state?.uploads ?? []).some(
          (upload) =>
            upload.state === "uploading" ||
            upload.state === "processing" ||
            upload.state === "finishing",
        );
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

/** Starts the job that writes the draft (and makes sure the render has a thumbnail). */
export function useDraftForYouTube(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      renderNumber: number;
      feedback: string | null;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/youtube/draft",
        {
          params: { path: { project_id: projectId } },
          body: {
            render_number: input.renderNumber,
            feedback: input.feedback,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the draft (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: youtubePanelKey(projectId) }),
        queryClient.invalidateQueries({ queryKey: thumbnailsKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** What the owner confirmed when pressing Upload. */
export type YouTubeUploadRequest = {
  renderNumber: number;
  channelRowId: number;
  draftVersion: number;
  privacy: YouTubePrivacy;
  madeForKids: boolean;
  syntheticMedia: boolean;
  notifySubscribers: boolean;
  captions: boolean;
};

/** Checks everything again on the server, then starts the upload. */
export function useUploadToYouTube(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: YouTubeUploadRequest) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/youtube/uploads",
        {
          params: { path: { project_id: projectId } },
          body: {
            render_number: input.renderNumber,
            channel_row_id: input.channelRowId,
            draft_version: input.draftVersion,
            privacy: input.privacy,
            made_for_kids: input.madeForKids,
            synthetic_media: input.syntheticMedia,
            notify_subscribers: input.notifySubscribers,
            captions: input.captions,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the upload (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: youtubePanelKey(projectId) }),
        queryClient.invalidateQueries({ queryKey: CHANNELS_KEY }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Which upload, and which failed step (none: the whole upload, or Finish). */
export type YouTubeRetryRequest = {
  uploadId: number;
  step?: "thumbnail" | "captions";
};

/**
 * Tries a failed upload again, finishes the thumbnail and captions of one that gave up waiting,
 * or tries one failed step again. What was done is not done again.
 */
export function useRetryYouTubeUpload(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ uploadId, step }: YouTubeRetryRequest) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/youtube/uploads/{upload_id}/retry",
        {
          params: { path: { project_id: projectId, upload_id: uploadId } },
          body: { step: step ?? null },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not try the upload again (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: youtubePanelKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Saves the owner's edit as the next version of the draft. */
export function useSaveYouTubeDraft(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      renderNumber: number;
      title: string;
      description: string;
      hashtags: string[];
    }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/youtube/draft",
        {
          params: { path: { project_id: projectId } },
          body: {
            render_number: input.renderNumber,
            title: input.title,
            description: input.description,
            hashtags: input.hashtags,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not save the draft (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: (state, input) => {
      queryClient.setQueryData(
        youtubePanelRenderKey(projectId, input.renderNumber),
        state,
      );
      return queryClient.invalidateQueries({
        queryKey: youtubePanelKey(projectId),
      });
    },
  });
}
