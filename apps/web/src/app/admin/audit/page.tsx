"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminAuditRow, adminApi, downloadCsv } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Button, Card } from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  bug_verify: "verified a bug",
  bug_reject: "rejected a bug",
  bug_verified: "verified a bug",
  role_changed: "changed a role",
  impersonate: "viewed as a user",
  contribution_refunded: "refunded a contribution",
  contributions_exported: "exported contributions",
};

export default function AdminAuditPage() {
  const [rows, setRows] = useState<AdminAuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [actions, setActions] = useState<string[]>([]);
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  useEffect(() => {
    adminApi.auditActions().then(setActions).catch(() => {});
  }, []);

  const load = useCallback(() => {
    adminApi
      .audit(action || undefined, since || undefined, until ? `${until}T23:59:59` : undefined)
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch(() => {});
  }, [action, since, until]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AdminShell>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="rounded-lg border border-stone-300 px-3 py-2 text-sm"
        >
          <option value="">All actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <label className="text-sm text-stone-500">
          From{" "}
          <input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            className="rounded-lg border border-stone-300 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="text-sm text-stone-500">
          To{" "}
          <input
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            className="rounded-lg border border-stone-300 px-2 py-1.5 text-sm"
          />
        </label>
        <span className="text-sm text-stone-500">{total} actions</span>
        <Button
          variant="soft"
          className="ml-auto"
          onClick={() =>
            downloadCsv(
              adminApi.auditCsvUrl(
                action || undefined,
                since || undefined,
                until ? `${until}T23:59:59` : undefined
              ),
              "futureroots-audit-log.csv"
            )
          }
        >
          Download CSV
        </Button>
      </div>

      <Card className="p-0">
        <ul className="divide-y divide-stone-100">
          {rows.map((r) => (
            <li key={r.id} className="flex items-start justify-between gap-4 px-4 py-3">
              <div className="min-w-0">
                <p className="text-sm text-stone-900">
                  <span className="font-medium">{r.admin_name}</span>{" "}
                  {ACTION_LABEL[r.action] ?? r.action}
                  {r.target ? <span className="text-stone-400"> · {r.target}</span> : null}
                </p>
                {Object.keys(r.detail).length > 0 && (
                  <p className="mt-0.5 truncate font-mono text-xs text-stone-400">
                    {JSON.stringify(r.detail)}
                  </p>
                )}
              </div>
              <span className="shrink-0 text-xs text-stone-400">
                {new Date(r.created_at).toLocaleString()}
              </span>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-stone-500">
              No actions match these filters.
            </li>
          )}
        </ul>
      </Card>
    </AdminShell>
  );
}
