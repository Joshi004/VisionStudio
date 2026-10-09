import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId, PROJECTS_KEY } from "./projects";
import type { components } from "./schema";

/** The newest automatic run of a project: where it is, what stopped it, what a start asks. */
export type AutoGenerateState = components["schemas"]["AutoGenerateOut"];
/** One step of the run (transcribe, propose scenes, ... final render). */
export type AutoStep = components["schemas"]["StepOut"];
/** Something a scene (or the project) needs: a scene that failed every try, or a block. */
export type AutoProblem = components["schemas"]["ProblemOut"];
/** What the user has confirmed when starting. Every flag is false unless set. */
export type AutoFlags = components["schemas"]["AutoGenerateRequest"];

/** The run's query lives under the project's key, so a job action refreshes it too. */
export function autoGenerateKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "auto-generate"] as const;
}

async function fetchAutoGenerate(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/auto-generate", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the automatic flow (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * Changes whenever the run moves: another run, another status, or any step changing its status
 * or its count. The rest of the page follows it.
 */
function progressSignature(data: AutoGenerateState): string {
  const steps = data.steps.map((step) => `${step.key}:${step.status}:${step.done}/${step.total}`);
  return `${data.job?.id ?? "none"}:${data.job?.status ?? "none"}:${steps.join(",")}`;
}

/**
 * The newest automatic run of the project and where it is. Reads the database only. It is
 * loaded again every few seconds while the run is waiting or running.
 *
 * A run makes the jobs of the other sections one after the other, so between two of them no
 * job may be active and those sections would stop checking. Each time the run moves, the whole
 * page is loaded again instead.
 */
export function useAutoGenerate(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: autoGenerateKey(projectId),
    queryFn: () => fetchAutoGenerate(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) => (isJobActive(current.state.data?.job) ? ACTIVE_POLL_MS : false),
  });

  const signature = query.data ? progressSignature(query.data) : null;
  const lastSignature = useRef(signature);
  useEffect(() => {
    // The first answer is not a change: the other sections load themselves.
    const before = lastSignature.current;
    if (signature !== null && before !== null && signature !== before) {
      void invalidateAfterJobAction(queryClient);
    }
    lastSignature.current = signature;
  }, [signature, queryClient]);

  return query;
}

/**
 * Starts a run (every step to the final video, paid calls included) and returns at once. The
 * page follows its progress by itself. After a refused start the page may be showing old data
 * (a job began, the transcript changed), so the run's state is loaded again.
 */
export function useStartAutoGenerate(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (flags: AutoFlags) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/auto-generate",
        { params: { path: { project_id: projectId } }, body: flags },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the automatic flow (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
    onError: (error) => {
      if (error instanceof ApiError && [404, 409, 422].includes(error.status)) {
        void queryClient.invalidateQueries({ queryKey: autoGenerateKey(projectId) });
      }
    },
  });
}
