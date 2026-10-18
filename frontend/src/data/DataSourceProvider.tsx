"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { ApiSource } from "./apiSource";
import { FixtureSource } from "./fixtureSource";
import { scenario } from "./scenario";
import type { DataSource } from "./source";

// "api" serves the FastAPI app through the /api/v1 rewrite; anything else plays the fixture.
function createDataSource(): DataSource {
  return process.env.NEXT_PUBLIC_CHECKMATE_SOURCE === "api" ? new ApiSource() : new FixtureSource(scenario);
}

const DataSourceContext = createContext<DataSource | null>(null);

/** `source` lets a component test supply its own adapter; the app always omits it. */
export function DataSourceProvider({
  children,
  source: given,
}: {
  children: ReactNode;
  source?: DataSource;
}) {
  const [source] = useState(() => given ?? createDataSource());
  return <DataSourceContext.Provider value={source}>{children}</DataSourceContext.Provider>;
}

export function useDataSource(): DataSource {
  const source = useContext(DataSourceContext);
  if (!source) throw new Error("useDataSource needs a DataSourceProvider");
  return source;
}
