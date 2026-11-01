import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { AccountBar } from "./account-bar";
import { DemoGate } from "./demo-gate";
import "./theme.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brimline",
  description: "Production planning for a fictional made-to-order 3D-print and CNC shop.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <Link href="/" className="brand">
            Brimline
          </Link>
          <nav aria-label="Main">
            <Link href="/orders">Orders</Link>
            <Link href="/quotes">Quotes</Link>
            <Link href="/price-rules">Prices</Link>
            <Link href="/board">Board</Link>
            <Link href="/queues">Queues</Link>
            <Link href="/search">Search</Link>
            <Link href="/materials">Materials</Link>
            <Link href="/dispatch">Dispatch</Link>
            <Link href="/reports">Reports</Link>
          </nav>
          {/* Reads the session cookie, so it streams in behind its own boundary. */}
          <Suspense fallback={<span className="muted">…</span>}>
            <AccountBar />
          </Suspense>
        </header>
        {/* Hosted demo only: a waking-up screen while the engine sleeps, and a banner. */}
        {process.env.DEMO_WAKE_CHECK === "1" ? (
          <Suspense fallback={<p className="page muted">Checking the demo is awake…</p>}>
            <DemoGate>{children}</DemoGate>
          </Suspense>
        ) : (
          children
        )}
      </body>
    </html>
  );
}
