"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminBugRow, adminApi } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

const CHIP: Record<AdminBugRow["status"], string> = {
  pending: "bg-amber-100 text-amber-800",
  verified: "bg-emerald-100 text-emerald-800",
  rejected: "bg-stone-200 text-stone-600",
};

// Points are a testnet concept; main-site issue reports earn the reporter nothing
const VERIFY_LABEL = process.env.NEXT_PUBLIC_TESTNET === "1" ? "Verify (+250)" : "Verify";

export default function AdminBugsPage() {
  const [bugs, setBugs] = useState<AdminBugRow[]>([]);
  const [filter, setFilter] = useState<"pending" | "all">("pending");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    adminApi.bugs(filter === "pending" ? "pending" : undefined).then(setBugs).catch(() => {});
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  async function decide(id: string, decision: "verify" | "reject") {
    setBusyId(id);
    try {
      await adminApi.decideBug(id, decision);
      load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AdminShell>
      <div className="mb-4 flex gap-2">
        {(["pending", "all"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
              filter === f ? "bg-emerald-700 text-white" : "bg-stone-100 text-stone-600"
            }`}
          >
            {f === "pending" ? "Pending" : "All"}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {bugs.map((b) => (
          <Card key={b.id}>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-stone-900">{b.title}</h3>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${CHIP[b.status]}`}>
                    {b.status}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-sm text-stone-600">{b.body}</p>
                <p className="mt-2 text-xs text-stone-400">
                  from {b.reporter}
                  {b.media_id ? " · screenshot attached" : ""}
                </p>
              </div>
              {b.status === "pending" && (
                <div className="flex shrink-0 flex-col gap-2">
                  <button
                    onClick={() => decide(b.id, "verify")}
                    disabled={busyId === b.id}
                    className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
                  >
                    {VERIFY_LABEL}
                  </button>
                  <button
                    onClick={() => decide(b.id, "reject")}
                    disabled={busyId === b.id}
                    className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm font-medium text-stone-600 hover:bg-stone-50 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          </Card>
        ))}
        {bugs.length === 0 && (
          <Card className="text-center text-stone-500">
            No {filter === "pending" ? "pending " : ""}bug reports.
          </Card>
        )}
      </div>
    </AdminShell>
  );
}
