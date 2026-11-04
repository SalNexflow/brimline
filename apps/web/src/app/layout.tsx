import type { Metadata } from "next";
import { Suspense } from "react";

import { THEME_SCRIPT } from "@/lib/theme";

import { AccountBar } from "./account-bar";
import { DemoGate } from "./demo-gate";
import { SideNav, SideNavLinks } from "./side-nav";
import { ThemeSwitch } from "./theme-switch";
import "./theme.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brimline",
  description: "Production planning for a fictional made-to-order 3D-print and CNC shop.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The script in <head> may set data-theme before React loads; that attribute is expected.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* The saved theme, applied before the first paint (lib/theme.ts). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        {/* The current page is only known per request, so the marked nav streams in. */}
        <Suspense fallback={<SideNavLinks path="" />}>
          <SideNav />
        </Suspense>
        <div className="shell">
          <header className="topbar">
            <ThemeSwitch />
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
