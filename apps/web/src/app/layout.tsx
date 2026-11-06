import type { Metadata } from "next";

import { THEME_SCRIPT } from "@/lib/theme";

import "./theme.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brimline",
  description: "Production planning for a fictional made-to-order 3D-print and CNC shop.",
};

/** Every page: the theme and the colours. The app's frame (rail, account, the hosted demo's waking
    check) is in (app)/layout.tsx; the front page has its own, lighter one (D202). */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The script in <head> may set data-theme before React loads; that attribute is expected.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* The saved theme, applied before the first paint (lib/theme.ts). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
