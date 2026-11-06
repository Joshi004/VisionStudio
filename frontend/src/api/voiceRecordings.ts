import { useMutation, useQueryClient } from "@tanstack/react-query";

import { invalidateAfterJobAction } from "./jobs";
import { uploadError } from "./projects";
import type { components } from "./schema";
import { speechAudioKey } from "./speechAudio";

export type SceneRecording = components["schemas"]["SceneRecordingOut"];

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
