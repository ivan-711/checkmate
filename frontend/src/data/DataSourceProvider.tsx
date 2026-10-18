"use client";

import { usePathname } from "next/navigation";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { ApiSource } from "./apiSource";
import { FixtureSource } from "./fixtureSource";
import { scenario } from "./scenario";
import type { DataSource } from "./source";

// "api" serves the FastAPI app through the /api/v1 rewrite; anything else plays the fixture.
function createDataSource(queueRoute: boolean): DataSource {
  return process.env.NEXT_PUBLIC_CHECKMATE_SOURCE === "api" || queueRoute
    ? new ApiSource()
    : new FixtureSource(scenario);
}

const DataSourceContext = createContext<DataSource | null>(null);

export function DataSourceProvider({ children }: { children: ReactNode }) {
  const queueRoute = usePathname().startsWith("/queue");
  const source = useMemo(() => createDataSource(queueRoute), [queueRoute]);
  return <DataSourceContext.Provider value={source}>{children}</DataSourceContext.Provider>;
}

export function useDataSource(): DataSource {
  const source = useContext(DataSourceContext);
  if (!source) throw new Error("useDataSource needs a DataSourceProvider");
  return source;
}
