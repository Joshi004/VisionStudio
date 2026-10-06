import { useIsFetching, useQueryClient } from "@tanstack/react-query";

export function useRefreshAll() {
  const queryClient = useQueryClient();
  const isRefreshing = useIsFetching() > 0;

  function refresh() {
    void queryClient.invalidateQueries();
  }

  return { refresh, isRefreshing };
}
