import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export function useRefreshAll() {
  const queryClient = useQueryClient();
  // Only the user's own Refresh shows a spinner. The checks that run by themselves while
  // a job is going (and the status checks) must not make the button flash.
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function refresh() {
    setIsRefreshing(true);
    try {
      await queryClient.invalidateQueries();
    } finally {
      setIsRefreshing(false);
    }
  }

  return { refresh, isRefreshing };
}
