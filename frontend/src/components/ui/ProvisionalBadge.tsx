"use client";

import { useQuery } from "@tanstack/react-query";
import { useDataSource } from "@/data/DataSourceProvider";

/** The contract's "provisional" badge: shown while the session's hero is the pre-20:00 pick. */
export function ProvisionalBadge() {
  const source = useDataSource();
  const session = useQuery({ queryKey: ["session"], queryFn: () => source.getSession() });
  if (!session.data?.heroProvisional) return null;
  return (
    <span
      data-testid="hero-provisional-badge"
      title="The hero scenario is provisional until the 20:00 selection."
      className="inline-flex h-9 items-center rounded border border-ink-2 px-3 text-[14px] font-medium text-ink-2"
    >
      provisional
    </span>
  );
}
