"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminContribution, adminApi, downloadCsv, formatMoney } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Button, Card, ErrorNote, Input, Label, Modal } from "@/components/ui";

const CHIP: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-stone-200 text-stone-600",
};

const STATUSES = ["", "succeeded", "pending", "failed", "refunded"];

export default function AdminContributionsPage() {
  const [rows, setRows] = useState<AdminContribution[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [refundTarget, setRefundTarget] = useState<AdminContribution | null>(null);
  const [refundAmount, setRefundAmount] = useState("");
  const [refundError, setRefundError] = useState("");
  const [refundBusy, setRefundBusy] = useState(false);

  const load = useCallback(() => {
    adminApi
      .contributions(q || undefined, status || undefined)
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch(() => {});
  }, [q, status]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  function openRefund(c: AdminContribution) {
    setRefundTarget(c);
    setRefundAmount("");
    setRefundError("");
  }

  function closeRefund() {
    setRefundTarget(null);
    setRefundAmount("");
    setRefundError("");
  }

  async function submitRefund() {
    if (!refundTarget) return;
    const c = refundTarget;
    const remaining = c.amount_cents - c.refunded_cents;
    let amountCents: number | undefined;
    if (refundAmount.trim() !== "") {
      const dollars = parseFloat(refundAmount);
      if (!(dollars > 0)) {
        setRefundError("Enter an amount greater than zero.");
        return;
      }
      amountCents = Math.round(dollars * 100);
      if (amountCents > remaining) {
        setRefundError(`That's more than the ${formatMoney(remaining, c.currency)} remaining.`);
        return;
      }
    }
    setRefundBusy(true);
    setRefundError("");
    try {
      await adminApi.refund(c.id, amountCents);
      closeRefund();
      load();
    } catch (err) {
      setRefundError(err instanceof Error ? err.message : "The refund didn't go through. Please try again.");
    } finally {
      setRefundBusy(false);
    }
  }

  async function reconcile(c: AdminContribution) {
    setBusyId(c.id);
    try {
      await adminApi.reconcile(c.id);
      load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AdminShell>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search contributor or child"
          className="w-56 rounded-lg border border-stone-300 px-3 py-2 text-sm"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-stone-300 px-3 py-2 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s === "" ? "All statuses" : s}
            </option>
          ))}
        </select>
        <span className="text-sm text-stone-500">{total} total</span>
        <Button
          variant="soft"
          className="ml-auto"
          onClick={() =>
            downloadCsv(
              adminApi.contributionsCsvUrl(q || undefined, status || undefined),
              "futureroots-contributions.csv"
            )
          }
        >
          Download CSV
        </Button>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="hidden items-center gap-4 border-b border-stone-200 bg-stone-50 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-stone-500 sm:flex">
          <span className="flex-1">Contributor</span>
          <span className="w-28">For child</span>
          <span className="w-24 text-center">Status</span>
          <span className="w-24 text-right">Amount</span>
          <span className="w-20" />
        </div>
        <ul className="divide-y divide-stone-100">
          {rows.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">
                  {c.contributor_id ? (
                    <a href={`/admin/users/${c.contributor_id}`} className="text-emerald-800 underline">
                      {c.contributor_name}
                    </a>
                  ) : (
                    <span className="text-stone-900">{c.contributor_name}</span>
                  )}
                </p>
                {c.provider_payment_id && (
                  <p
                    className="truncate font-mono text-[11px] text-stone-400"
                    title="Stripe PaymentIntent id"
                  >
                    {c.provider_payment_id}
                  </p>
                )}
              </div>
              <p className="w-28 truncate text-sm text-stone-600">{c.child_name}</p>
              <span className="w-24 text-center">
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${CHIP[c.status] ?? "bg-stone-100 text-stone-600"}`}>
                  {c.status}
                </span>
              </span>
              <span className="w-24 text-right tabular-nums">
                <span className="font-bold text-emerald-800">
                  {formatMoney(c.amount_cents, c.currency)}
                </span>
                {c.refunded_cents > 0 && (
                  <span className="block text-[11px] font-medium text-stone-400">
                    {formatMoney(c.refunded_cents, c.currency)} refunded
                  </span>
                )}
              </span>
              <span className="w-20 text-right">
                {c.status === "succeeded" && (
                  <button
                    onClick={() => openRefund(c)}
                    className="text-xs font-medium text-red-600 underline hover:text-red-700 disabled:opacity-50"
                  >
                    {c.refunded_cents > 0 ? "Refund more" : "Refund"}
                  </button>
                )}
                {c.status === "pending" && (
                  <button
                    onClick={() => reconcile(c)}
                    disabled={busyId === c.id}
                    className="text-xs font-medium text-emerald-700 underline hover:text-emerald-800 disabled:opacity-50"
                    title="Check the live payment status and resolve this record"
                  >
                    Reconcile
                  </button>
                )}
              </span>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-stone-500">No contributions found.</li>
          )}
        </ul>
      </Card>

      <Modal open={refundTarget !== null} onClose={closeRefund} title="Issue a refund">
        {refundTarget && (
          <RefundModalBody
            c={refundTarget}
            amount={refundAmount}
            onAmountChange={setRefundAmount}
            error={refundError}
            busy={refundBusy}
            onCancel={closeRefund}
            onConfirm={submitRefund}
          />
        )}
      </Modal>
    </AdminShell>
  );
}

function RefundModalBody({
  c,
  amount,
  onAmountChange,
  error,
  busy,
  onCancel,
  onConfirm,
}: {
  c: AdminContribution;
  amount: string;
  onAmountChange: (v: string) => void;
  error: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const remaining = c.amount_cents - c.refunded_cents;
  return (
    <div className="space-y-4">
      <dl className="space-y-2 rounded-xl bg-stone-50 px-4 py-3 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-stone-500">Contributor</dt>
          <dd className="font-medium text-stone-900">{c.contributor_name}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-stone-500">For child</dt>
          <dd className="font-medium text-stone-900">{c.child_name}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-stone-500">Original amount</dt>
          <dd className="font-medium text-stone-900">{formatMoney(c.amount_cents, c.currency)}</dd>
        </div>
        {c.refunded_cents > 0 && (
          <div className="flex justify-between gap-4">
            <dt className="text-stone-500">Already refunded</dt>
            <dd className="font-medium text-stone-900">
              {formatMoney(c.refunded_cents, c.currency)}
            </dd>
          </div>
        )}
        <div className="flex justify-between gap-4 border-t border-stone-200 pt-2">
          <dt className="text-stone-500">Remaining</dt>
          <dd className="font-bold text-emerald-800">{formatMoney(remaining, c.currency)}</dd>
        </div>
      </dl>

      <div>
        <Label htmlFor="refund-amount">Amount to refund (USD)</Label>
        <Input
          id="refund-amount"
          type="number"
          min="0"
          step="0.01"
          inputMode="decimal"
          placeholder="0.00"
          value={amount}
          onChange={(e) => onAmountChange(e.target.value)}
          autoFocus
        />
        <p className="mt-1 text-xs text-stone-500">
          Leave blank to refund the full remaining {formatMoney(remaining, c.currency)}.
        </p>
      </div>

      <ErrorNote>{error}</ErrorNote>

      <div className="flex justify-end gap-3">
        <Button variant="soft" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button variant="danger" onClick={onConfirm} disabled={busy}>
          {busy ? "Refunding…" : "Refund"}
        </Button>
      </div>
    </div>
  );
}
