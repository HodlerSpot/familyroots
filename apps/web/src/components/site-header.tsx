"use client";

import { usePathname } from "next/navigation";
import { Logo } from "@/components/logo";

export function SiteHeader() {
  const pathname = usePathname();
  // The landing page opens with the full hero lockup — no header needed there
  if (pathname === "/") return null;

  return (
    <header className="border-b border-stone-200 bg-white">
      <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-3">
        <a href="/" aria-label="FutureRoots home">
          <Logo size="sm" />
        </a>
        <span className="hidden text-sm text-stone-500 sm:block">
          Building Generational Wealth &amp; Memories
        </span>
      </div>
    </header>
  );
}
