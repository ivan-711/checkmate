"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useDataSource } from "@/data/DataSourceProvider";
import { ModeBadge } from "./ModeBadge";
import { ResetButton } from "./ResetButton";

const TABS = [
  { href: "/frontdesk", label: "FrontDesk" },
  { href: "/", label: "Case" },
] as const;

export function Header() {
  const pathname = usePathname();
  const { mode } = useDataSource();
  return (
    <header className="flex h-14 items-center gap-6 border-b border-border-subtle bg-surface px-4">
      <span className="text-[24px] font-semibold tracking-tight">CheckMate</span>
      <nav aria-label="Main">
        <ul className="flex gap-1">
          {TABS.map(({ href, label }) => {
            const current = pathname === href;
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={current ? "page" : undefined}
                  className={`inline-flex h-11 items-center border-b-2 px-3 text-[18px] ${
                    current ? "border-accent font-semibold text-ink-1" : "border-transparent text-ink-2"
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <ModeBadge mode={mode} />
        <ResetButton />
      </div>
    </header>
  );
}
