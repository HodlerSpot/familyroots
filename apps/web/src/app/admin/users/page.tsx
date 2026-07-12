"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AdminUserRow, adminApi, beginImpersonation } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

export default function AdminUsersPage() {
  const router = useRouter();
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

  async function toggleDisabled(u: AdminUserRow) {
    const verb = u.disabled ? "re-enable" : "disable";
    if (!confirm(`${verb === "disable" ? "Disable" : "Re-enable"} ${u.email}? ${u.disabled ? "They will be able to sign in again." : "They will be signed out and blocked from logging in."}`)) return;
    setBusyId(u.id);
    try {
      await adminApi.setStatus(u.id, !u.disabled);
      load();
    } finally {
      setBusyId(null);
    }
  }

  async function viewAs(u: AdminUserRow) {
    setBusyId(u.id);
    try {
      const session = await adminApi.impersonate(u.id);
      beginImpersonation(session.access_token, session.display_name || session.email);
      router.push("/family");
    } catch {
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
          <span className="w-16 text-center">Families</span>
          <span className="w-16 text-center">Children</span>
          <span className="w-64 text-right">Manage</span>
        </div>
        <ul className="divide-y divide-stone-100">
          {rows.map((u) => (
            <li
              key={u.id}
              className={`flex items-center gap-4 px-4 py-3 ${u.disabled ? "bg-stone-50/70" : ""}`}
            >
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 truncate font-medium">
                  <a href={`/admin/users/${u.id}`} className="text-emerald-800 underline">
                    {u.display_name}
                  </a>
                  {u.disabled && (
                    <span className="rounded-full bg-stone-200 px-2 py-0.5 text-[10px] font-semibold uppercase text-stone-600">
                      disabled
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-stone-500">{u.email}</p>
                <p className="truncate text-[11px] text-stone-400">
                  Joined {new Date(u.created_at).toLocaleDateString()} · Last login{" "}
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : "never"}
                </p>
              </div>
              <span className="w-16 text-center tabular-nums text-stone-700">{u.family_count}</span>
              <span className="w-16 text-center tabular-nums text-stone-700">{u.child_count}</span>
              {/* fixed-width actions cell so numeric columns always align */}
              <div className="flex w-64 shrink-0 items-center justify-end gap-2">
                {u.role !== "admin" && !u.disabled && (
                  <button
                    onClick={() => viewAs(u)}
                    disabled={busyId === u.id}
                    className="rounded-lg border border-stone-300 px-2.5 py-1 text-xs font-medium text-stone-600 hover:bg-stone-50 disabled:opacity-50"
                    title="View the app as this user (support mode)"
                  >
                    View as
                  </button>
                )}
                {u.role !== "admin" && (
                  <button
                    onClick={() => toggleDisabled(u)}
                    disabled={busyId === u.id}
                    className={`rounded-lg border px-2.5 py-1 text-xs font-medium disabled:opacity-50 ${
                      u.disabled
                        ? "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                        : "border-red-200 text-red-600 hover:bg-red-50"
                    }`}
                  >
                    {u.disabled ? "Enable" : "Disable"}
                  </button>
                )}
                <button
                  onClick={() => toggleRole(u)}
                  disabled={busyId === u.id}
                  className={`w-24 shrink-0 rounded-full px-3 py-1 text-center text-xs font-semibold disabled:opacity-50 ${
                    u.role === "admin"
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-stone-100 text-stone-600"
                  }`}
                  title="Click to toggle admin"
                >
                  {u.role === "admin" ? "admin ✓" : "make admin"}
                </button>
              </div>
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
