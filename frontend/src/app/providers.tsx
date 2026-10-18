"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { DeskProvider } from "@/components/desk/DeskContext";
import { LiveRegionProvider } from "@/components/ui/LiveRegion";
import { LATEST_MATCH_RUN_KEY } from "@/components/ui/ResetButton";
import { DataSourceProvider } from "@/data/DataSourceProvider";

const UNDO_WINDOW_MS = 5_000;

function createQueryClient() {
  // Decisions carry an Idempotency-Key per intent; a silent retry would hide failures.
  const client = new QueryClient({ defaultOptions: { queries: { retry: 1 }, mutations: { retry: 0 } } });
  // The match-run receipt is only ever written by Resolve; keep it while the tab is open, even
  // when no screen is showing it, so the work queue can draw the funnel later.
  client.setQueryDefaults(LATEST_MATCH_RUN_KEY, { gcTime: Infinity, staleTime: Infinity });
  return client;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <DataSourceProvider>
        <LiveRegionProvider>
          <DeskProvider>
            {children}
            <Toaster position="bottom-right" duration={UNDO_WINDOW_MS} />
          </DeskProvider>
        </LiveRegionProvider>
      </DataSourceProvider>
    </QueryClientProvider>
  );
}
