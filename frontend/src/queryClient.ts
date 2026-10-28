import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      // Data younger than this is reused when a panel is opened again.
      // Invalidation and polling ignore it, so changes still show at once.
      staleTime: 20_000,
      refetchOnWindowFocus: false,
    },
  },
});
