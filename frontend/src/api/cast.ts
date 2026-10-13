import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId, PROJECTS_KEY } from "./projects";
import { scenesKey } from "./scenes";
import type { components } from "./schema";

/** A project's cast: its characters and places, and what can be done with them next. */
export type Cast = components["schemas"]["CastOut"];
/** One character or place, with its reference prompt and picture. */
export type CastMember = components["schemas"]["CastMemberOut"];
export type CastKind = CastMember["kind"];
/** What to change in a member. Only the fields that are sent change. */
export type CastMemberEdit = components["schemas"]["CastMemberPatch"];

/** The cast query lives under the project's key, so saving the script refreshes it. */
export function castKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "cast"] as const;
}

async function fetchCast(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/cast", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the cast (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The characters and places, and the reference picture jobs, in one list. */
export function castMembers(cast: Cast): CastMember[] {
  return [...cast.characters, ...cast.locations];
}

/** True while a job the cast carries is waiting or running. */
export function castHasActiveJob(cast: Cast | undefined): boolean {
  if (cast === undefined) {
    return false;
  }
  return (
    isJobActive(cast.extract_job) ||
    isJobActive(cast.assign_job) ||
    castMembers(cast).some((member) => isJobActive(member.prompt_job) || isJobActive(member.image_job))
  );
}

/**
 * The project's cast. It is loaded again every few seconds while any of its jobs is waiting
 * or running.
 */
export function useCast(projectId: number) {
  return useQuery({
    queryKey: castKey(projectId),
    queryFn: () => fetchCast(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (castHasActiveJob(query.state.data) ? ACTIVE_POLL_MS : false),
  });
}

/**
 * After a refused or failed start the page may be showing old data, so the cast and the scenes
 * are loaded again.
 */
function useCastStartMutation<TVariables, TResult>(
  projectId: number,
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    // A start creates a job: the job lists, the cast, the scenes and the banner's waiting count
    // all change.
    onSuccess: () => invalidateAfterJobAction(queryClient),
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        void queryClient.invalidateQueries({ queryKey: castKey(projectId) });
        void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
      }
    },
  });
}

/**
 * Finds the characters and places in the script (a paid call to the language model) and
 * returns at once. It replaces the whole cast, so `confirmReplace` must be true when there is
 * one already (the server answers 409 until then).
 */
export function useExtractCast(projectId: number) {
  return useCastStartMutation(projectId, async ({ confirmReplace }: { confirmReplace: boolean }) => {
    const { data, error, response } = await api.POST("/api/projects/{project_id}/extract-cast", {
      params: { path: { project_id: projectId } },
      body: { confirm_replace: confirmReplace },
    });
    if (!data) {
      throw new ApiError(
        detailMessage(error, `Could not start finding the cast (HTTP ${response.status}).`),
        response.status,
      );
    }
    return data;
  });
}

/**
 * Chooses the character and the place of every scene (a paid call to the language model) and
 * returns at once. A choice the user made by hand is kept.
 */
export function useAssignCast(projectId: number) {
  return useCastStartMutation(projectId, async () => {
    const { data, error, response } = await api.POST("/api/projects/{project_id}/assign-cast", {
      params: { path: { project_id: projectId } },
    });
    if (!data) {
      throw new ApiError(
        detailMessage(error, `Could not start choosing the cast (HTTP ${response.status}).`),
        response.status,
      );
    }
    return data;
  });
}

/** Writes the prompt for a member's reference picture (a paid call), and returns at once. */
export function useWriteReferencePrompt(projectId: number) {
  return useCastStartMutation(
    projectId,
    async ({
      kind,
      memberId,
      generateAfter,
    }: {
      kind: CastKind;
      memberId: number;
      generateAfter: boolean;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/cast/{kind}/{member_id}/write-reference-prompt",
        {
          params: { path: { project_id: projectId, kind, member_id: memberId } },
          body: { generate_after: generateAfter },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the prompt (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/**
 * Makes a member's reference picture on the GPU server and returns at once. A member with no
 * prompt gets one written first, and the picture follows by itself.
 */
export function useGenerateReference(projectId: number) {
  return useCastStartMutation(
    projectId,
    async ({ kind, memberId }: { kind: CastKind; memberId: number }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/cast/{kind}/{member_id}/generate-reference",
        { params: { path: { project_id: projectId, kind, member_id: memberId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the picture (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/** Saves the text of a character or place. The answer holds the whole cast afterwards. */
export function useEditCastMember(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      kind,
      memberId,
      edit,
    }: {
      kind: CastKind;
      memberId: number;
      edit: CastMemberEdit;
    }) => {
      const { data, error, response } = await api.PATCH(
        "/api/projects/{project_id}/cast/{kind}/{member_id}",
        {
          params: { path: { project_id: projectId, kind, member_id: memberId } },
          body: edit,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: async (data) => {
      // A check that is still on its way would arrive after this answer and show the old
      // cast again, so it is cancelled first.
      await queryClient.cancelQueries({ queryKey: castKey(projectId), exact: true });
      queryClient.setQueryData(castKey(projectId), data);
      // A scene's image prompt is out of date when the description it was written from changed.
      void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
    },
  });
}

/**
 * Chooses the character and the place one scene shows (null for none). The choice is the
 * user's: the AI never overwrites it. The answer holds the scenes afterwards.
 */
export function useSetSceneCast(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      sceneId,
      characterId,
      locationId,
    }: {
      sceneId: number;
      characterId: number | null;
      locationId: number | null;
    }) => {
      const { data, error, response } = await api.PATCH(
        "/api/projects/{project_id}/scenes/{scene_id}/cast",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { character_id: characterId, location_id: locationId },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the choice (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: async (data) => {
      await queryClient.cancelQueries({ queryKey: scenesKey(projectId), exact: true });
      queryClient.setQueryData(scenesKey(projectId), data);
      // The members show how many scenes show them.
      void queryClient.invalidateQueries({ queryKey: castKey(projectId) });
    },
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
        void queryClient.invalidateQueries({ queryKey: castKey(projectId) });
      }
    },
  });
}
