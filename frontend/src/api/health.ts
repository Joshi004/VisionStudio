import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type { components } from "./schema";

export type HealthResponse = components["schemas"]["HealthResponse"];

async function fetchHealth(): Promise<HealthResponse> {
  const { data, error, response } = await api.GET("/api/health");

  // The backend returns the same HealthResponse body for both 200 (ok) and
  // 503 (degraded); openapi-fetch only puts 2xx bodies in `data`, so a 503
  // body shows up in `error` instead. Both are a successful health check.
  if (response.status === 200 && data) {
    return data;
  }
  if (response.status === 503 && error) {
    return error;
  }

  throw new Error(`Unexpected response from /api/health: ${response.status}`);
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });
}
