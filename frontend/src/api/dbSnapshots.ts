import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { ACTIVE_POLL_MS, STATUS_POLL_MS } from "./polling";
import type { components } from "./schema";

export type DbSnapshotsStatus = components["schemas"]["SnapshotsStatusOut"];

const DB_SNAPSHOTS_KEY = ["db-snapshots"] as const;

async function fetchDbSnapshots(): Promise<DbSnapshotsStatus> {
  const { data, response } = await api.GET("/api/db-snapshots");
  if (!data) {
    throw new ApiError(
      `Could not load the database snapshots (HTTP ${response.status}).`,
      response.status,
    );
  }
  return data;
}

/** The snapshot status. It is asked again quickly while a snapshot is being made. */
export function useDbSnapshots() {
  return useQuery({
    queryKey: DB_SNAPSHOTS_KEY,
    queryFn: fetchDbSnapshots,
    refetchInterval: (query) => (query.state.data?.running ? ACTIVE_POLL_MS : STATUS_POLL_MS),
  });
}

export function useMakeDbSnapshot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/db-snapshots");
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the snapshot (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // The new status says a snapshot is running, so the page starts polling at once. The header
    // reads its warning from the health check.
    onSuccess: (data) => {
      queryClient.setQueryData(DB_SNAPSHOTS_KEY, data);
      return queryClient.invalidateQueries({ queryKey: ["health"] });
    },
  });
}
