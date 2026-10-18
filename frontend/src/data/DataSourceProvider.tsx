"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { ApiSource } from "./apiSource";
import { FixtureSource } from "./fixtureSource";
import { scenario } from "./scenario";
import type { DataSource } from "./source";

// "api" serves the FastAPI app through the /api/v1 rewrite; anything else plays the fixture.
// One source for the whole build and the whole visit: every screen, the work queue included,
// reads the same one, so moving between screens keeps the session's state.
function createDataSource(): DataSource {
  return process.env.NEXT_PUBLIC_CHECKMATE_SOURCE === "api" ? new ApiSource() : new FixtureSource(scenario);
}

const DataSourceContext = createContext<DataSource | null>(null);

export function DataSourceProvider({ children }: { children: ReactNode }) {
  const [source] = useState(createDataSource);
  return <DataSourceContext.Provider value={source}>{children}</DataSourceContext.Provider>;
}

export function useDataSource(): DataSource {
  const source = useContext(DataSourceContext);
  if (!source) throw new Error("useDataSource needs a DataSourceProvider");
  return source;
}
