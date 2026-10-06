import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { GPU_KEY } from "./gpu";
import type { components } from "./schema";

export type SettingItem = components["schemas"]["SettingItem"];

const SETTINGS_KEY = ["settings"] as const;

async function fetchSettings() {
  const { data, response } = await api.GET("/api/settings");
  if (!data) {
    throw new ApiError(`Could not load the settings (HTTP ${response.status}).`, response.status);
  }
  return data;
}

export function useSettings() {
  return useQuery({ queryKey: SETTINGS_KEY, queryFn: fetchSettings });
}

/** A changed URL also changes which stored GPU results (connection, API, banner) still apply. */
function useRefreshAfterChange() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: SETTINGS_KEY }),
      queryClient.invalidateQueries({ queryKey: GPU_KEY }),
    ]);
}

export function useSaveSetting() {
  const refresh = useRefreshAfterChange();
  return useMutation({
    mutationFn: async ({ key, value }: { key: string; value: string | number }) => {
      const { data, error, response } = await api.PUT("/api/settings/{key}", {
        params: { path: { key } },
        body: { value },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the setting (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: refresh,
  });
}

export function useResetSetting() {
  const refresh = useRefreshAfterChange();
  return useMutation({
    mutationFn: async (key: string) => {
      const { data, error, response } = await api.DELETE("/api/settings/{key}", {
        params: { path: { key } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not reset the setting (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: refresh,
  });
}
