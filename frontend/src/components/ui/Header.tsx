"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useDataSource } from "@/data/DataSourceProvider";
import { ModeBadge } from "./ModeBadge";
import { ProvisionalBadge } from "./ProvisionalBadge";
import { ResetButton } from "./ResetButton";

const TABS = [
  { href: "/frontdesk", label: "FrontDesk" },
  { href: "/", label: "Case" },
  { href: "/queue", label: "Work queue" },
] as const;

export function Header() {
  const pathname = usePathname();
  const { mode } = useDataSource();
  return (
    <header className="flex min-h-14 flex-wrap items-center gap-x-6 gap-y-2 border-b border-border-subtle bg-surface px-4 max-[640px]:gap-x-2 max-[640px]:py-2">
      <span className="text-[24px] font-semibold tracking-tight">CheckMate</span>
      <nav aria-label="Main" className="max-[640px]:order-3 max-[640px]:w-full">
        <ul className="flex gap-1 max-[640px]:grid max-[640px]:grid-cols-3">
          {TABS.map(({ href, label }) => {
            const current = href === "/queue" ? pathname.startsWith(href) : pathname === href;
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={current ? "page" : undefined}
                  className={`inline-flex h-11 items-center border-b-2 px-3 text-[18px] max-[640px]:justify-center max-[640px]:px-1 max-[640px]:text-[16px] ${
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
      <div className="ml-auto flex items-center gap-3 max-[640px]:gap-2">
        <span className="max-[640px]:hidden">
          <ProvisionalBadge />
        </span>
        <ModeBadge mode={mode} />
        <ResetButton />
      </div>
    </header>
  );
}
