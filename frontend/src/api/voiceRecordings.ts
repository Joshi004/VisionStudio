import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { isValidProjectId, uploadError } from "./projects";
import type { components } from "./schema";
import { speechAudioKey } from "./speechAudio";

export type SceneRecording = components["schemas"]["SceneRecordingOut"];
export type FullRecording = components["schemas"]["FullRecordingOut"];
export type FullRecordingState = components["schemas"]["FullRecordingStateOut"];
export type FullScript = components["schemas"]["FullScriptOut"];
export type SceneBoundary = components["schemas"]["SceneBoundaryOut"];

/** Where a recording came from: the browser's recorder, or a file the person chose. */
export type RecordingOrigin = "browser" | "upload";

/**
 * Sends one recording of one scene of a recorded explainer (REC-003). It becomes the scene's take
 * when the answer comes. `unitsVersion` is the version of the scene's speech units that the
 * person was shown, so a scene whose text changed in the meantime is refused. The server checks
 * the size and the type; it stays the judge.
 */
export function useUploadSceneRecording(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      sceneId: string;
      unitsVersion: number;
      origin: RecordingOrigin;
      file: Blob;
    }) => {
      const query = new URLSearchParams({
        origin: input.origin,
        units_version: String(input.unitsVersion),
      });
      const response = await fetch(
        `/api/projects/${projectId}/voice-recordings/scenes/${encodeURIComponent(
          input.sceneId,
        )}?${query.toString()}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: input.file,
        },
      );
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as SceneRecording;
    },
    // A refusal can mean something changed, so the state is loaded again either way.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: speechAudioKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * Under the speech-audio key, so every refresh of the speech audio refreshes this too (a full
 * recording changes which scenes have a take).
 */
function fullRecordingKey(projectId: number) {
  return [...speechAudioKey(projectId), "full-recording"] as const;
}

/**
 * The script of the whole video to read, and where the newest full recording stands (REC-004).
 * Only for a recorded explainer: pass `enabled` false for any other. It is loaded again every
 * few seconds while the recording is being transcribed or split.
 */
export function useFullRecording(projectId: number, enabled: boolean) {
  return useQuery({
    queryKey: fullRecordingKey(projectId),
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/projects/{project_id}/voice-recordings/full",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not load the full recording (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    enabled: enabled && isValidProjectId(projectId),
    refetchInterval: (current) => {
      const stage = current.state.data?.newest?.stage;
      return stage === "transcribing" || stage === "splitting"
        ? ACTIVE_POLL_MS
        : false;
    },
  });
}

/**
 * Sends a recording of the whole script (REC-004). `scriptKey` is the key of the script the
 * person was shown, so a script that changed in the meantime is refused. The recording is
 * transcribed by a job afterwards; the server checks the size and the type and stays the judge.
 */
export function useUploadFullRecording(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      scriptKey: string;
      origin: RecordingOrigin;
      file: Blob;
    }) => {
      const query = new URLSearchParams({
        origin: input.origin,
        script_key: input.scriptKey,
      });
      const response = await fetch(
        `/api/projects/${projectId}/voice-recordings/full?${query.toString()}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: input.file,
        },
      );
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as components["schemas"]["FullRecordingStoredOut"];
    },
    // A refusal can mean something changed, so the state is loaded again either way.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: speechAudioKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** "Try again" on a full recording whose transcription or split failed. */
export function useRetryFullRecording(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (recordingId: number) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/voice-recordings/full/{recording_id}/retry",
        {
          params: {
            path: { project_id: projectId, recording_id: recordingId },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not try again (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: speechAudioKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** The owner's decision on one tight boundary (REC-005). `cutS` is for `cut_at` only. */
export type BoundaryDecisionInput =
  | { afterSceneId: string; beforeSceneId: string; decision: "keep" }
  | {
      afterSceneId: string;
      beforeSceneId: string;
      decision: "cut_at";
      cutS: number;
    };

/**
 * Decides one tight boundary of the newest full recording (REC-005): keep it as is, or cut at a
 * point. The server checks the cut point and stays the judge. The recording is split again by a
 * job once nothing is left to decide.
 */
export function useDecideBoundary(projectId: number, recordingId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: BoundaryDecisionInput) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/voice-recordings/full/{recording_id}/boundaries",
        {
          params: {
            path: { project_id: projectId, recording_id: recordingId },
          },
          body: {
            after_scene_id: input.afterSceneId,
            before_scene_id: input.beforeSceneId,
            decision: input.decision,
            cut_s: input.decision === "cut_at" ? input.cutS : null,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not save the decision (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: speechAudioKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** "Keep all as is": keeps every tight boundary nobody has decided yet (REC-005). */
export function useKeepAllBoundaries(projectId: number, recordingId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/voice-recordings/full/{recording_id}/boundaries/keep-all",
        {
          params: {
            path: { project_id: projectId, recording_id: recordingId },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not keep the boundaries (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: speechAudioKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * The address of a short WAV of a full recording, from `startS` to `endS` seconds (the server
 * gives at most 10 seconds and cuts the end short at the end of the recording). Used by the
 * boundary player and the cut point editor (REC-005).
 */
export function recordingExcerptUrl(
  projectId: number,
  recordingId: number,
  startS: number,
  endS: number,
): string {
  const query = new URLSearchParams({
    start_s: startS.toFixed(3),
    end_s: endS.toFixed(3),
  });
  return `/api/projects/${projectId}/voice-recordings/full/${recordingId}/excerpt?${query.toString()}`;
}

/** The two seconds either side of a cut that the player and the previews play. */
export const PREVIEW_SPAN_S = 2;
