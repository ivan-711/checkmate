"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { LiveRegionProvider } from "@/components/ui/LiveRegion";
import { DataSourceProvider } from "@/data/DataSourceProvider";

const UNDO_WINDOW_MS = 5_000;

function createQueryClient() {
  // Decisions carry an Idempotency-Key per intent; a silent retry would hide failures.
  return new QueryClient({ defaultOptions: { queries: { retry: 1 }, mutations: { retry: 0 } } });
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <DataSourceProvider>
        <LiveRegionProvider>
          {children}
          <Toaster position="bottom-right" duration={UNDO_WINDOW_MS} />
        </LiveRegionProvider>
      </DataSourceProvider>
    </QueryClientProvider>
  );
}
