"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { CiteContext as CiteState, CiteField } from "@/lib/desk";

// The React side of lib/desk.ts's CiteContext: the evidence rail (L4) sets the cite, the Organism
// (L3) reads it. One context object, so both lanes light the same field.
const NONE: CiteState = { cite: null, setCite: () => {} };
const Context = createContext<CiteState>(NONE);

/** Wraps the stage with a cite the caller controls (tests, a rail that owns the state). */
export function CiteContextProvider({ value, children }: { value: CiteState; children: ReactNode }) {
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** Wraps the stage with its own cite state: the rail calls setCite on hover and focus. */
export function CiteProvider({ children }: { children: ReactNode }) {
  const [cite, setCite] = useState<CiteField | null>(null);
  const value = useMemo<CiteState>(() => ({ cite, setCite }), [cite]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useCite(): CiteState {
  return useContext(Context);
}
