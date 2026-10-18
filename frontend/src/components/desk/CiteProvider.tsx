"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { CiteContext, CiteField } from "@/lib/desk";

// Without a provider nothing is cited: a card renders the same on the queue and in a test.
const NONE: CiteContext = { cite: null, setCite: () => {} };
const Cite = createContext<CiteContext>(NONE);

/** Hover-to-cite (CONCEPT.md §5, touch 6). The evidence rail writes the cited field; the Organism's
 * records read it and wash that field in both. On the Desk, `value` is DeskContext's cite, so the
 * header and Organism share it; `initial` is for server renders and tests. */
export function CiteProvider({
  initial = null,
  value,
  children,
}: {
  initial?: CiteField | null;
  value?: CiteContext;
  children: ReactNode;
}) {
  const [cite, setCite] = useState<CiteField | null>(initial);
  const own = useMemo<CiteContext>(() => ({ cite, setCite }), [cite]);
  return <Cite.Provider value={value ?? own}>{children}</Cite.Provider>;
}

export function useCite(): CiteContext {
  return useContext(Cite);
}
