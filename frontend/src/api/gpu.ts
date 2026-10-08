import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { STATUS_POLL_MS } from "./polling";
import type { components } from "./schema";

export type ConnectionTest = components["schemas"]["ConnectionTest"];
export type ConnectionTestResult = components["schemas"]["ConnectionTestResult"];
export type ContractCheck = components["schemas"]["ContractCheckOut"];
export type SourceCheck = components["schemas"]["SourceCheckOut"];
export type GpuStatus = components["schemas"]["GpuStatus"];
export type ContractOverview = components["schemas"]["ContractOverviewOut"];
export type ContractSourceOverview = components["schemas"]["SourceOverviewOut"];
export type ContractSources = components["schemas"]["ContractSourcesOut"];
export type ContractSourceIn = components["schemas"]["ContractSourceIn"];
export type ContractDiff = components["schemas"]["ContractDiffOut"];
export type ApproveResponse = components["schemas"]["ApproveResponse"];

/** Every GPU query starts with this key, so one call refreshes them all. */
export const GPU_KEY = ["gpu"] as const;
const GPU_CONNECTION_KEY = ["gpu", "connection"] as const;
const GPU_STATUS_KEY = ["gpu", "status"] as const;
const GPU_CONTRACT_KEY = ["gpu", "contract"] as const;

async function fetchConnection() {
  const { data, response } = await api.GET("/api/gpu/connection");
  if (!data) {
    throw new ApiError(
      `Could not load the last connection test (HTTP ${response.status}).`,
      response.status,
    );
  }
  return data;
}

/** The last stored test result. This reads the database; it never calls the GPU server. */
export function useGpuConnection() {
  return useQuery({ queryKey: GPU_CONNECTION_KEY, queryFn: fetchConnection });
}

export function useTestGpuConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, response } = await api.POST("/api/gpu/connection/test");
      if (!data) {
        throw new ApiError(
          `The connection test could not run (HTTP ${response.status}).`,
          response.status,
        );
      }
      return data;
    },
    // A test changes the stored server result, the contract check and the banner.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GPU_KEY }),
  });
}

async function fetchStatus() {
  const { data, response } = await api.GET("/api/gpu/status");
  if (!data) {
    throw new ApiError(`Could not load the GPU status (HTTP ${response.status}).`, response.status);
  }
  return data;
}

/**
 * What the banner reads. Stored state only: it never calls the GPU server. It is loaded
 * again every 30 seconds, so a change shows without a Refresh.
 */
export function useGpuStatus() {
  return useQuery({
    queryKey: GPU_STATUS_KEY,
    queryFn: fetchStatus,
    refetchInterval: STATUS_POLL_MS,
  });
}

async function fetchContract() {
  const { data, response } = await api.GET("/api/gpu/contract");
  if (!data) {
    throw new ApiError(
      `Could not load the recorded GPU API (HTTP ${response.status}).`,
      response.status,
    );
  }
  return data;
}

/** The approved API, any change waiting for approval and the last check. Stored state only. */
export function useContract() {
  return useQuery({ queryKey: GPU_CONTRACT_KEY, queryFn: fetchContract });
}

/** Source name to the fingerprint the user reviewed. Empty for a first approval. */
export type ExpectedFingerprints = Record<string, string>;

export function useApproveContract() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (expected: ExpectedFingerprints) => {
      const { data, error, response } = await api.POST("/api/gpu/contract/approve", {
        body: { expected },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not approve the API (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GPU_KEY }),
  });
}

export function useSaveContractSources() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sources: ContractSourceIn[]) => {
      const { data, error, response } = await api.PUT("/api/gpu/contract/sources", {
        body: { sources },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the sources (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GPU_KEY }),
  });
}

export function useResetContractSources() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.DELETE("/api/gpu/contract/sources");
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not reset the sources (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GPU_KEY }),
  });
}
