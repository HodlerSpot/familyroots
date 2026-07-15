"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { loadStripe } from "@stripe/stripe-js";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { api, ApiError, formatMoney, FundAccountStatus, getToken } from "@/lib/api";
import { Button, Card, ErrorNote, Input } from "@/components/ui";

const PRESETS = [1000, 2500, 5000];
const stripeKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;
const stripePromise = stripeKey ? loadStripe(stripeKey) : null;

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
  // Stripe step: set when the API returns a client_secret
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [pendingAmount, setPendingAmount] = useState(0);
  // Card-processing amount from the API; net = gross - fee, no client math beyond that
  const [pendingFee, setPendingFee] = useState(0);
  // Gifts only flow when the child's Future Fund is active
  const [fundStatus, setFundStatus] = useState<FundAccountStatus | null>(null);

  const load = useCallback(async () => {
    try {
      const [family, status] = await Promise.all([
        api.familyDetail(familyId),
        api.fundStatus(childId),
      ]);
      setChildName(family.children.find((c) => c.id === childId)?.first_name ?? "");
      setFundStatus(status.account_status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      } else {
        setError("We couldn't load this page. Please try the link again");
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

  async function start() {
    setBusy(true);
    setError("");
    try {
      const contribution = await api.createContribution(childId, {
        amount_cents: effectiveAmount,
        message: message || undefined,
      });
      setPendingFee(contribution.fee_cents);
      if (contribution.client_secret) {
        if (!stripePromise) {
          setError("Payments aren't configured on this site yet. Please try again later.");
          setBusy(false);
          return;
        }
        setPendingAmount(effectiveAmount);
        setClientSecret(contribution.client_secret);
        setBusy(false);
      } else {
        await api.confirmContribution(contribution.id);
        setDone(true);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  if (done) {
    const finalAmount = pendingAmount || effectiveAmount;
    return (
      <Card className="mx-auto max-w-lg space-y-4 text-center">
        <div className="text-5xl">💝</div>
        <h1 className="text-2xl font-bold text-emerald-900">
          You just added to {childName}&apos;s future
        </h1>
        <p className="text-stone-600">
          Your {formatMoney(finalAmount)} gift{message ? " and your note are" : " is"} on
          {childName ? ` ${childName}'s` : " their"} timeline for the whole family to see,
          and it will be waiting for {childName || "them"} for years to come.
        </p>
        {pendingFee > 0 && (
          <p className="text-stone-600">
            {formatMoney(finalAmount - pendingFee)} is on its way to{" "}
            {childName ? `${childName}'s` : "their"} account.
          </p>
        )}
        <Button onClick={() => router.push(`/family/${familyId}`)} className="w-full">
          See the family feed
        </Button>
      </Card>
    );
  }

  if (clientSecret && stripePromise) {
    return (
      <Card className="mx-auto max-w-lg space-y-6">
        <div className="text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-mark.png" alt="" className="mx-auto h-14" />
          <h1 className="mt-2 text-2xl font-bold text-emerald-900">
            {formatMoney(pendingAmount)} for {childName || "their"} future
          </h1>
        </div>
        {pendingFee > 0 && (
          <div className="rounded-xl bg-emerald-50/50 p-4">
            <dl className="space-y-1">
              <div className="flex items-baseline justify-between gap-4 text-base text-stone-700">
                <dt>Your gift</dt>
                <dd className="text-right tabular-nums">{formatMoney(pendingAmount)}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-4 text-sm text-stone-500">
                <dt>Card processing</dt>
                <dd className="text-right tabular-nums">{formatMoney(pendingFee)}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-4 pt-2 text-lg font-semibold text-emerald-900">
                <dt>🌳 Goes straight to {childName || "them"}</dt>
                <dd className="text-right tabular-nums">
                  {formatMoney(pendingAmount - pendingFee)}
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-stone-500">
              This covers what the card costs to process. FutureRoots doesn&apos;t
              profit from gifts; the rest is all{" "}
              {childName ? `${childName}'s` : "theirs"}.
            </p>
          </div>
        )}
        <Elements
          stripe={stripePromise}
          options={{ clientSecret, appearance: { variables: { colorPrimary: "#047857" } } }}
        >
          <PaymentForm amount={pendingAmount} onPaid={() => setDone(true)} />
        </Elements>
        <button
          onClick={() => setClientSecret(null)}
          className="w-full text-center text-sm text-stone-500 underline"
        >
          ← Change amount
        </button>
      </Card>
    );
  }

  // Never show a payment form until we know the fund can receive gifts.
  if (fundStatus === null) {
    return error ? (
      <div className="mx-auto max-w-lg">
        <ErrorNote>{error}</ErrorNote>
      </div>
    ) : (
      <p className="text-center text-stone-500">One moment…</p>
    );
  }

  if (fundStatus !== "active") {
    const paused = fundStatus === "restricted";
    return (
      <Card className="mx-auto max-w-lg space-y-4 text-center">
        <div className="text-5xl">🌳</div>
        <h1 className="text-2xl font-bold text-emerald-900">
          {paused
            ? `Gifts to ${childName || "this little one"} are paused just now`
            : `${childName ? `${childName}'s` : "Their"} Future Fund is on its way`}
        </h1>
        <p className="text-stone-600">
          {paused
            ? "The family is updating a detail. Please try again soon."
            : `${childName ? `${childName}'s` : "The"} family is getting the Future Fund ready. We'll be glad to see you back soon.`}
        </p>
        <Button
          variant="soft"
          className="w-full"
          onClick={() => router.push(`/family/${familyId}/child/${childId}`)}
        >
          Back to the vault
        </Button>
      </Card>
    );
  }

  return (
    <Card className="mx-auto max-w-lg space-y-6">
      <div className="text-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo-mark.png" alt="" className="mx-auto h-14" />
        <h1 className="mt-2 text-2xl font-bold text-emerald-900">
          Add to {childName || "their"} future
        </h1>
        <p className="mt-1 text-stone-600">A gift today, a head start tomorrow.</p>
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
        onClick={start}
        disabled={busy || effectiveAmount < 100}
        className="w-full text-lg"
      >
        {busy ? "One moment…" : `Continue with ${formatMoney(effectiveAmount)}`}
      </Button>
      <p className="text-center text-xs text-stone-400">
        Gifts are added to {childName || "the child"}&apos;s Future Fund and go
        straight to the account their family chose.
      </p>
    </Card>
  );
}

function PaymentForm({ amount, onPaid }: { amount: number; onPaid: () => void }) {
  const stripe = useStripe();
  const elements = useElements();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function pay(e: React.FormEvent) {
    e.preventDefault();
    if (!stripe || !elements) return;
    setBusy(true);
    setError("");
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: window.location.href },
      redirect: "if_required",
    });
    if (result.error) {
      setError(result.error.message ?? "The payment didn't go through. Please try again");
      setBusy(false);
    } else {
      onPaid();
    }
  }

  return (
    <form onSubmit={pay} className="space-y-4">
      <PaymentElement />
      <ErrorNote>{error}</ErrorNote>
      <Button type="submit" disabled={busy || !stripe} className="w-full text-lg">
        {busy ? "Sending…" : `Send ${formatMoney(amount)} with love`}
      </Button>
    </form>
  );
}
