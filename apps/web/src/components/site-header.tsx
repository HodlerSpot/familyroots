"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api, getToken } from "@/lib/api";
import { Logo } from "@/components/logo";

export function SiteHeader() {
  const pathname = usePathname();
  const [isAdmin, setIsAdmin] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setIsAdmin(false);
      setAuthed(false);
      return;
    }
    setAuthed(true);
    api
      .me()
      .then((u) => setIsAdmin(u.role === "admin"))
      .catch(() => setIsAdmin(false));
  }, [pathname]);

  // The landing page opens with the full hero lockup — no header needed there
  if (pathname === "/") return null;

  const navLink = (href: string, label: string) => {
    const active = pathname === href;
    return (
      <a
        href={href}
        className={`px-1 py-1 text-sm font-medium transition-colors ${
          active ? "text-emerald-800" : "text-stone-600 hover:text-emerald-800"
        }`}
      >
        {label}
      </a>
    );
  };

  return (
    <header className="border-b border-stone-200 bg-white">
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-6 py-3">
        <a href="/" aria-label="FutureRoots home">
          <Logo size="sm" />
        </a>
        <div className="flex items-center gap-3 sm:gap-4">
          {authed && (
            <nav className="flex items-center gap-3 sm:gap-4">
              {navLink("/contributions", "My contributions")}
              {navLink("/settings", "Settings")}
            </nav>
          )}
          {isAdmin ? (
            <a
              href="/admin"
              className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-800"
            >
              Command center
            </a>
          ) : (
            !authed && (
              <span className="hidden text-sm text-stone-500 sm:block">
                Building Generational Wealth &amp; Memories
              </span>
            )
          )}
        </div>
      </div>
    </header>
  );
}
