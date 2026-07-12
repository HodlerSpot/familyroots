import type { Metadata } from "next";
import "./globals.css";
import { SiteHeader } from "@/components/site-header";
import { TestnetRoot } from "@/components/testnet/root";

export const metadata: Metadata = {
  title: "FutureRoots: Building Generational Wealth & Memories",
  description:
    "A private space where your family shares memories, celebrates milestones, and builds a future together.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">
        <TestnetRoot>
          <SiteHeader />
          <main className="mx-auto max-w-3xl px-6 py-10">{children}</main>
        </TestnetRoot>
      </body>
    </html>
  );
}
