"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api, getToken } from "@/lib/api";
import { Logo } from "@/components/logo";

export function SiteHeader() {
  const pathname = usePathname();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setIsAdmin(false);
      return;
    }
    api
      .me()
      .then((u) => setIsAdmin(u.role === "admin"))
      .catch(() => setIsAdmin(false));
  }, [pathname]);

  // The landing page opens with the full hero lockup — no header needed there
  if (pathname === "/") return null;

  return (
    <header className="border-b border-stone-200 bg-white">
      <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-3">
        <a href="/" aria-label="FutureRoots home">
          <Logo size="sm" />
        </a>
        {isAdmin ? (
          <a
            href="/admin"
            className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-800"
          >
            Command center
          </a>
        ) : (
          <span className="hidden text-sm text-stone-500 sm:block">
            Building Generational Wealth &amp; Memories
          </span>
        )}
      </div>
    </header>
  );
}
