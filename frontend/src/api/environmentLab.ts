import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { LAB_KEY } from "./imageLab";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import type { components } from "./schema";

export type LibraryEnvironment = components["schemas"]["EnvironmentOut"];
export type EnvironmentIn = components["schemas"]["EnvironmentIn"];
export type EnvironmentPatch = components["schemas"]["EnvironmentPatch"];
export type EnvironmentVersion = components["schemas"]["EnvironmentVersionOut"];
export type EnvironmentReference = components["schemas"]["ReferenceOut"];
export type EnvironmentStateRecord = components["schemas"]["EnvironmentStateOut"];
export type ReferenceCandidate = components["schemas"]["ReferenceCandidateOut"];

const PAGE_SIZE = 20;

/** Every environment library query starts with this key. */
export const ENVIRONMENT_LAB_KEY = ["lab", "environments"] as const;
const listKey = [...ENVIRONMENT_LAB_KEY, "list"] as const;
const detailKey = (environmentId: number | null) =>
  [...ENVIRONMENT_LAB_KEY, "detail", environmentId] as const;
const versionsKey = (environmentId: number | null) =>
  [...ENVIRONMENT_LAB_KEY, "versions", environmentId] as const;
const referencesKey = (environmentId: number | null) =>
  [...ENVIRONMENT_LAB_KEY, "references", environmentId] as const;
const statesKey = (environmentId: number | null) =>
  [...ENVIRONMENT_LAB_KEY, "states", environmentId] as const;

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

/**
 * Is an attempt still being made? Its prompt is being written, or a candidate's picture is
 * being drawn. Only then is the page asked for fresh data every few seconds.
 */
export function referenceIsBusy(reference: EnvironmentReference): boolean {
  return (
    reference.status === "writing_prompt" ||
    reference.candidates.some((candidate) => isJobActive(candidate.job))
  );
}

/**
 * Anything done here can change the library, the Image lab (a candidate is an ordinary Image
 * lab run) and the jobs. Only the queries on screen are fetched again; the others are marked
 * old.
 */
function refreshAfterChange(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ENVIRONMENT_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: LAB_KEY }),
    invalidateAfterJobAction(queryClient),
  ]);
}

// --- The library -------------------------------------------------------------------------------

async function fetchEnvironments(includeArchived: boolean, beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/environments", {
    params: {
      query: { include_archived: includeArchived, before_id: beforeId, limit: PAGE_SIZE },
    },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the environments");
  }
  return data;
}

/** The environments, newest first, a page at a time. Archived ones only when asked for. */
export function useLibraryEnvironments(includeArchived: boolean) {
  return useInfiniteQuery({
    queryKey: [...listKey, includeArchived],
    queryFn: ({ pageParam }) => fetchEnvironments(includeArchived, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
  });
}

async function fetchEnvironment(environmentId: number) {
  const { data, error, response } = await api.GET("/api/lab/environments/{environment_id}", {
    params: { path: { environment_id: environmentId } },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the environment");
  }
  return data;
}

/** One environment. Nothing is loaded while `environmentId` is null. */
export function useLibraryEnvironment(environmentId: number | null) {
  return useQuery({
    queryKey: detailKey(environmentId),
    queryFn: () => fetchEnvironment(environmentId as number),
    enabled: environmentId !== null,
  });
}

export function useCreateEnvironment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: EnvironmentIn) => {
      const { data, error, response } = await api.POST("/api/lab/environments", { body });
      if (!data) {
        throw failure(error, response.status, "The environment was not saved");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Changes the profile (which adds a version), archives or unarchives, or both at once. */
export function useEditEnvironment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { environmentId: number; body: EnvironmentPatch }) => {
      const { data, error, response } = await api.PATCH("/api/lab/environments/{environment_id}", {
        params: { path: { environment_id: input.environmentId } },
        body: input.body,
      });
      if (!data) {
        throw failure(error, response.status, "The environment was not saved");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

// --- Versions ----------------------------------------------------------------------------------

async function fetchVersions(environmentId: number) {
  const { data, error, response } = await api.GET(
    "/api/lab/environments/{environment_id}/versions",
    { params: { path: { environment_id: environmentId } } },
  );
  if (!data) {
    throw failure(error, response.status, "Could not load the versions");
  }
  return data;
}

/** Every version of an environment, newest first, each with its own picture. */
export function useEnvironmentVersions(environmentId: number | null) {
  return useQuery({
    queryKey: versionsKey(environmentId),
    queryFn: () => fetchVersions(environmentId as number),
    enabled: environmentId !== null,
  });
}

// --- States ------------------------------------------------------------------------------------

async function fetchStates(environmentId: number) {
  const { data, error, response } = await api.GET(
    "/api/lab/environments/{environment_id}/states",
    { params: { path: { environment_id: environmentId } } },
  );
  if (!data) {
    throw failure(error, response.status, "Could not load the states");
  }
  return data;
}

/**
 * The named states of an environment (such as night), read-only. A story project's resolution
 * creates them and makes their pictures, so they are loaded again after any change.
 */
export function useEnvironmentStates(environmentId: number | null) {
  return useQuery({
    queryKey: statesKey(environmentId),
    queryFn: () => fetchStates(environmentId as number),
    enabled: environmentId !== null,
  });
}

// --- Reference pictures ------------------------------------------------------------------------

async function fetchReferences(environmentId: number) {
  const { data, error, response } = await api.GET(
    "/api/lab/environments/{environment_id}/references",
    { params: { path: { environment_id: environmentId } } },
  );
  if (!data) {
    throw failure(error, response.status, "Could not load the pictures");
  }
  return data;
}

/**
 * Every attempt to make a picture for an environment, newest first. They are loaded again every
 * few seconds while one is being made.
 */
export function useEnvironmentReferences(environmentId: number | null) {
  return useQuery({
    queryKey: referencesKey(environmentId),
    enabled: environmentId !== null,
    refetchInterval: (query) =>
      query.state.data?.some(referenceIsBusy) ? ACTIVE_POLL_MS : false,
    queryFn: () => fetchReferences(environmentId as number),
  });
}

/** Starts an attempt for the newest version: the prompt is written, then four are drawn. */
export function useStartReference() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (environmentId: number) => {
      const { data, error, response } = await api.POST(
        "/api/lab/environments/{environment_id}/references",
        { params: { path: { environment_id: environmentId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The picture could not be started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Makes a candidate the canonical picture of the version its attempt was made for. */
export function useChooseReference() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { referenceId: number; candidateId: number }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/environments/references/{reference_id}/choose",
        {
          params: { path: { reference_id: input.referenceId } },
          body: { candidate_id: input.candidateId },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The picture was not chosen");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}
