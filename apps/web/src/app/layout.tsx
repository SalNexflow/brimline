import type { Metadata } from "next";
import { Suspense } from "react";

import { AccountBar } from "./account-bar";
import { DemoGate } from "./demo-gate";
import { SideNav, SideNavLinks } from "./side-nav";
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
        {/* The current page is only known per request, so the marked nav streams in. */}
        <Suspense fallback={<SideNavLinks path="" />}>
          <SideNav />
        </Suspense>
        <div className="shell">
          <header className="topbar">
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
        </div>
      </body>
    </html>
  );
}
