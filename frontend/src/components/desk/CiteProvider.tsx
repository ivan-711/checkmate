"use client";

import { useMemo, useState, type ReactNode } from "react";
import { CiteContextProvider, useCite as useRecordCite } from "@/components/record/CiteContext";
import type { CiteContext, CiteField } from "@/lib/desk";

/** Hover-to-cite (CONCEPT.md §5, touch 6). The evidence rail writes the cited field; the Organism's
 * records read it and wash that field in both. On the Desk, `value` is DeskContext's cite, so the
 * header and Organism share it; `initial` is for server renders and tests. It provides the
 * Organism's own context (record/CiteContext), so the rail and the records read one object. */
export function CiteProvider({
  initial = null,
  value,
  children,
}: {
  initial?: CiteField | null;
  value?: CiteContext;
  children?: ReactNode;
}) {
  const [cite, setCite] = useState<CiteField | null>(initial);
  const own = useMemo<CiteContext>(() => ({ cite, setCite }), [cite]);
  return <CiteContextProvider value={value ?? own}>{children}</CiteContextProvider>;
}

export const useCite = useRecordCite;
