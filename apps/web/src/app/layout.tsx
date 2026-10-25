import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { AccountBar } from "./account-bar";
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
          </nav>
          {/* Reads the session cookie, so it streams in behind its own boundary. */}
          <Suspense fallback={<span className="muted">…</span>}>
            <AccountBar />
          </Suspense>
        </header>
        {children}
      </body>
    </html>
  );
}
