"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

// Simple line icons drawn for Brimline (24 x 24, stroke only), so no icon library is needed.
const ICONS: Record<string, ReactNode> = {
  orders: (
    <>
      <rect x="5" y="4" width="14" height="17" rx="3" />
      <path d="M9 9h6M9 13h6M9 17h3" />
    </>
  ),
  quotes: (
    <>
      <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4 4v-4h0.5A2.5 2.5 0 0 1 4 13.5z" />
      <path d="M8 8.5h8M8 12h5" />
    </>
  ),
  prices: (
    <>
      <path d="M12.5 3.5H19a1.5 1.5 0 0 1 1.5 1.5v6.5L11 21 3 13z" />
      <circle cx="16" cy="8" r="1.5" />
    </>
  ),
  board: (
    <>
      <path d="M4 4v16h16" />
      <path d="M7 8h6M10 12h8M8 16h5" />
    </>
  ),
  queues: (
    <>
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M3.5 6l1.2 1.2L7 5M3.5 12l1.2 1.2L7 11" />
      <circle cx="5" cy="18" r="1.2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="M15.5 15.5 20 20" />
    </>
  ),
  materials: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
      <path d="M12 4v5M12 15v5" />
    </>
  ),
  dispatch: (
    <>
      <path d="M4 12 20 4l-5 16-3.5-6.5z" />
      <path d="M11.5 13.5 20 4" />
    </>
  ),
  reports: (
    <>
      <path d="M4 20h16" />
      <path d="M7 16v-5M12 16V7M17 16v-8" />
    </>
  ),
};

const LINKS: { href: string; label: string; icon: string }[] = [
  { href: "/orders", label: "Orders", icon: "orders" },
  { href: "/quotes", label: "Quotes", icon: "quotes" },
  { href: "/price-rules", label: "Prices", icon: "prices" },
  { href: "/board", label: "Board", icon: "board" },
  { href: "/queues", label: "Queues", icon: "queues" },
  { href: "/search", label: "Search", icon: "search" },
  { href: "/materials", label: "Materials", icon: "materials" },
  { href: "/dispatch", label: "Dispatch", icon: "dispatch" },
  { href: "/reports", label: "Reports", icon: "reports" },
];

/** The main navigation with the current page marked. The path is only known at request time, so
    the layout streams this in and shows SideNavLinks without a marker until then. */
export function SideNav() {
  return <SideNavLinks path={usePathname()} />;
}

/** A slim icon rail that opens on hover or keyboard focus to show labels. The label is always in
    the link's name, so screen readers and tests read the same words. */
export function SideNavLinks({ path }: { path: string }) {
  return (
    <nav className="sidebar" aria-label="Main">
      <Link href="/" className="brand" aria-label="Brimline home">
        <span className="brand-mark" aria-hidden="true" />
        <span className="nav-label">Brimline</span>
      </Link>
      <div className="nav-links">
        {LINKS.map((l) => {
          const current = path === l.href || path.startsWith(`${l.href}/`);
          return (
            <Link key={l.href} href={l.href} className="nav-link" aria-current={current ? "page" : undefined}>
              <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                {ICONS[l.icon]}
              </svg>
              <span className="nav-label">{l.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
