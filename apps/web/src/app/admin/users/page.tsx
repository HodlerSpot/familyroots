"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminUserRow, adminApi } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

export default function AdminUsersPage() {
  const [rows, setRows] = useState<AdminUserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    adminApi
      .users(q || undefined)
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch(() => {});
  }, [q]);

  useEffect(() => {
    const t = setTimeout(load, 250); // debounce search
    return () => clearTimeout(t);
  }, [load]);

  async function toggleRole(u: AdminUserRow) {
    setBusyId(u.id);
    try {
      await adminApi.setRole(u.id, u.role === "admin" ? "user" : "admin");
      load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AdminShell>
      <div className="mb-4 flex items-center justify-between gap-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by name or email"
          className="w-full max-w-xs rounded-lg border border-stone-300 px-3 py-2 text-sm"
        />
        <span className="shrink-0 text-sm text-stone-500">{total} users</span>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="hidden items-center gap-4 border-b border-stone-200 bg-stone-50 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-stone-500 sm:flex">
          <span className="flex-1">User</span>
          <span className="w-20 text-center">Families</span>
          <span className="w-20 text-center">Children</span>
          <span className="w-24 text-right">Role</span>
        </div>
        <ul className="divide-y divide-stone-100">
          {rows.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-stone-900">{u.display_name}</p>
                <p className="truncate text-xs text-stone-500">{u.email}</p>
              </div>
              <span className="w-20 text-center tabular-nums text-stone-700">{u.family_count}</span>
              <span className="w-20 text-center tabular-nums text-stone-700">{u.child_count}</span>
              <button
                onClick={() => toggleRole(u)}
                disabled={busyId === u.id}
                className={`w-24 rounded-full px-3 py-1 text-right text-xs font-semibold disabled:opacity-50 ${
                  u.role === "admin"
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-stone-100 text-stone-600"
                }`}
                title="Click to toggle admin"
              >
                {u.role === "admin" ? "admin ✓" : "make admin"}
              </button>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-stone-500">No users found.</li>
          )}
        </ul>
      </Card>
    </AdminShell>
  );
}
