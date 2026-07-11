"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, formatMoney, getToken } from "@/lib/api";
import { Button, Card, ErrorNote, Input } from "@/components/ui";

const PRESETS = [1000, 2500, 5000];

export default function ContributePage() {
  const router = useRouter();
  const { id: familyId, childId } = useParams<{ id: string; childId: string }>();
  const [childName, setChildName] = useState("");
  const [amount, setAmount] = useState<number>(2500);
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const load = useCallback(async () => {
    try {
      const family = await api.familyDetail(familyId);
      setChildName(family.children.find((c) => c.id === childId)?.first_name ?? "");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      } else {
        setError("We couldn't load this page — please try the link again");
      }
    }
  }, [familyId, childId, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    load();
  }, [router, load]);

  const effectiveAmount = custom ? Math.round(parseFloat(custom) * 100) || 0 : amount;

  async function send() {
    setBusy(true);
    setError("");
    try {
      const contribution = await api.createContribution(childId, {
        amount_cents: effectiveAmount,
        message: message || undefined,
      });
      await api.confirmContribution(contribution.id);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong — please try again");
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Card className="mx-auto max-w-lg space-y-4 text-center">
        <div className="text-5xl">💝</div>
        <h1 className="text-2xl font-bold text-emerald-900">
          You just added to {childName}&apos;s future
        </h1>
        <p className="text-stone-600">
          Your {formatMoney(effectiveAmount)} gift{message ? " and your note are" : " is"} on
          {childName ? ` ${childName}'s` : " their"} timeline for the whole family to see —
          and it will be waiting for {childName || "them"} for years to come.
        </p>
        <Button onClick={() => router.push(`/family/${familyId}`)} className="w-full">
          See the family feed
        </Button>
      </Card>
    );
  }

  return (
    <Card className="mx-auto max-w-lg space-y-6">
      <div className="text-center">
        <div className="text-4xl">🌱</div>
        <h1 className="mt-2 text-2xl font-bold text-emerald-900">
          Add to {childName || "their"} future
        </h1>
        <p className="mt-1 text-stone-600">
          A gift today, a head start tomorrow.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {PRESETS.map((cents) => (
          <button
            key={cents}
            onClick={() => {
              setAmount(cents);
              setCustom("");
            }}
            className={`rounded-xl border-2 px-4 py-4 text-lg font-bold transition ${
              !custom && amount === cents
                ? "border-emerald-700 bg-emerald-50 text-emerald-900"
                : "border-stone-200 text-stone-700 hover:border-emerald-300"
            }`}
          >
            {formatMoney(cents)}
          </button>
        ))}
      </div>
      <Input
        placeholder="Or another amount ($)"
        type="number"
        min="1"
        step="0.01"
        value={custom}
        onChange={(e) => setCustom(e.target.value)}
      />
      <Input
        placeholder={`A note for ${childName || "them"} (optional)`}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        maxLength={2000}
      />
      <ErrorNote>{error}</ErrorNote>
      <Button
        onClick={send}
        disabled={busy || effectiveAmount < 100}
        className="w-full text-lg"
      >
        {busy ? "Sending…" : `Send ${formatMoney(effectiveAmount)} with love`}
      </Button>
      <p className="text-center text-xs text-stone-400">
        Gifts are added to {childName || "the child"}&apos;s future fund, safe until
        they&apos;re grown.
      </p>
    </Card>
  );
}
