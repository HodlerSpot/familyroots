// A single shared TanStack Query client for the app. Defaults are conservative
// for mobile networks; per-query tuning happens in the feature screens.
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});
