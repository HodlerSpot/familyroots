import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FutureRoots — Building Generational Wealth & Memories",
  description:
    "A private space where your family shares memories, celebrates milestones, and builds a future together.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">
        <header className="border-b border-stone-200 bg-white">
          <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
            <a href="/" className="text-xl font-bold text-emerald-800">
              🌱 FutureRoots
            </a>
            <span className="hidden text-sm text-stone-500 sm:block">
              Building Generational Wealth &amp; Memories
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-3xl px-6 py-10">{children}</main>
      </body>
    </html>
  );
}
