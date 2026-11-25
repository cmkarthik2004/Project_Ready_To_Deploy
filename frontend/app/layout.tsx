import type { Metadata, Viewport } from "next";
import AppShell from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "FinRAG — Financial Document Intelligence",
  description: "Upload financial documents, ask grounded questions with citations, and analyse extracted financial data.",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}
