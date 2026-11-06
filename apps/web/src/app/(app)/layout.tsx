import { Suspense, type ReactNode } from "react";

import { AccountBar } from "../account-bar";
import { DemoGate } from "../demo-gate";
import { SideNav, SideNavLinks } from "../side-nav";
import { ThemeSwitch } from "../theme-switch";

/** The app: the icon rail, the account bar, and on the hosted demo the waking check and banner in
    front of every page (sign-in included). */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <>
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
    </>
  );
}
