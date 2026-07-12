"use client";

// Admin command center shell: client-side role guard + sub-navigation.
// The real protection is server-side (every /admin API route is role-gated);
// this just keeps non-admins from seeing an empty, broken page.

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, getToken, UserOut } from "@/lib/api";

const NAV = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/bugs", label: "Bug reports" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/families", label: "Families" },
  { href: "/admin/contributions", label: "Contributions" },
];

export function AdminShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<"loading" | "denied" | "ok">("loading");
  const [me, setMe] = useState<UserOut | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    api
      .me()
      .then((u) => {
        setMe(u);
        setState(u.role === "admin" ? "ok" : "denied");
      })
      .catch(() => router.replace(`/login?next=${encodeURIComponent(pathname)}`));
  }, [router, pathname]);

  if (state === "loading") return <p className="text-stone-500">Loading…</p>;
  if (state === "denied") {
    return (
      <div className="mx-auto max-w-md rounded-2xl border border-stone-200 bg-white p-8 text-center">
        <div className="text-4xl">🔒</div>
        <h1 className="mt-2 text-xl font-bold text-stone-900">Admin access required</h1>
        <p className="mt-1 text-stone-600">This area is for platform operators.</p>
        <a href="/family" className="mt-4 inline-block text-sm font-medium text-emerald-700 underline">
          Back to your families
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-emerald-900">Command center</h1>
          <p className="text-sm text-stone-500">Signed in as {me?.email}</p>
        </div>
        <nav className="flex flex-wrap gap-1">
          {NAV.map((item) => {
            const active =
              item.href === "/admin" ? pathname === "/admin" : pathname.startsWith(item.href);
            return (
              <a
                key={item.href}
                href={item.href}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-emerald-700 text-white"
                    : "text-stone-600 hover:bg-stone-100"
                }`}
              >
                {item.label}
              </a>
            );
          })}
        </nav>
      </div>
      {children}
    </div>
  );
}
