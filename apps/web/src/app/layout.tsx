import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brimline",
  description: "Production planning for a fictional made-to-order 3D-print and CNC shop.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
