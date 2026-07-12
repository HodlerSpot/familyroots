"use client";

// Loud, persistent banner whenever an admin is viewing the app as a user.
// Exiting restores the admin's own session.

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { endImpersonation, impersonationLabel } from "@/lib/api";

export function ImpersonationBanner() {
  const router = useRouter();
  const pathname = usePathname();
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    setLabel(impersonationLabel());
  }, [pathname]);

  if (!label) return null;

  return (
    <div className="flex items-center justify-center gap-3 bg-amber-500 px-4 py-2 text-center text-sm font-semibold text-amber-950">
      <span>Viewing as {label} (support mode)</span>
      <button
        onClick={() => {
          endImpersonation();
          router.push("/admin/users");
        }}
        className="rounded-md bg-amber-950/20 px-3 py-1 text-amber-950 hover:bg-amber-950/30"
      >
        Exit
      </button>
    </div>
  );
}
