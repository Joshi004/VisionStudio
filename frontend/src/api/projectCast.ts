import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type Cast = components["schemas"]["CastOut"];
export type CastMember = components["schemas"]["CastMemberOut"];
export type CastMode = CastMember["mode"];
export type CastKind = "characters" | "environments";

/** What each mode does with a cast member that a story entry was matched to. */
export const CAST_MODE_LABELS: Record<CastMode, string> = {
  as_is: "Use as is",
  rewrite_text: "Keep look, rewrite text",
};

/**
 * The cast query of a project. It starts with the project's own key, like every other query of
 * the story, so saving the story refreshes it too.
 */
export function castKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "cast"] as const;
}

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

/** The library characters and environments the user put in the project's cast. */
export function useProjectCast(projectId: number) {
  return useQuery({
    queryKey: castKey(projectId),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/projects/{project_id}/cast", {
        params: { path: { project_id: projectId } },
      });
      if (!data) {
        throw failure(error, response.status, "Could not load the cast");
      }
      return data;
    },
    enabled: isValidProjectId(projectId),
  });
}

/**
 * A changed cast makes the discovered characters (or environments) out of date, and changes
 * what the later steps do with a linked entry, so every query of the project is marked old.
 */
function useRefreshProject(projectId: number) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: [...PROJECTS_KEY, projectId] });
}

type MemberInput = { kind: CastKind; libraryId: number };

/** Puts a library item in the cast, or changes the mode of one that is in it already. */
export function useSetCastMember(projectId: number) {
  const refresh = useRefreshProject(projectId);
  return useMutation({
    mutationFn: async (input: MemberInput & { mode: CastMode }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/cast/{kind}/{library_id}",
        {
          params: {
            path: { project_id: projectId, kind: input.kind, library_id: input.libraryId },
          },
          body: { mode: input.mode },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The cast was not changed");
      }
      return data;
    },
    onSettled: refresh,
  });
}

/** Takes a library item out of the cast. The item stays in its lab. */
export function useRemoveCastMember(projectId: number) {
  const refresh = useRefreshProject(projectId);
  return useMutation({
    mutationFn: async (input: MemberInput) => {
      const { error, response } = await api.DELETE(
        "/api/projects/{project_id}/cast/{kind}/{library_id}",
        {
          params: {
            path: { project_id: projectId, kind: input.kind, library_id: input.libraryId },
          },
        },
      );
      // The answer has no body (204), so success is the status and not `data`.
      if (!response.ok) {
        throw failure(error, response.status, "The item was not removed from the cast");
      }
    },
    onSettled: refresh,
  });
}
