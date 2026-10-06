import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError } from "./errors";
import type { components } from "./schema";

export type ConnectionTest = components["schemas"]["ConnectionTest"];

const GPU_CONNECTION_KEY = ["gpu", "connection"] as const;

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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GPU_CONNECTION_KEY }),
  });
}
