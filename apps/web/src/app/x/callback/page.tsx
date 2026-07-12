"use client";

// Where X sends the tester back after they approve the connection. Reads the
// ?code & ?state, hands them to the API to finish the handshake, then returns
// to the account page. Testnet-only; on the family build the API call 404s.

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { testnetApi } from "@/components/testnet/api";
import { Card } from "@/components/ui";

function XCallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [status, setStatus] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");
  const ran = useRef(false);

  useEffect(() => {
    // The state is single-use, so guard against React running this twice.
    if (ran.current) return;
    ran.current = true;

    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      setStatus("error");
      setMessage("That X sign-in was missing something. Please try again from your account.");
      return;
    }

    testnetApi
      .xCallback(code, state)
      .then(() => {
        setStatus("ok");
        setTimeout(() => router.replace("/account"), 1000);
      })
      .catch((err) => {
        setStatus("error");
        setMessage(
          err instanceof Error ? err.message : "We couldn't finish connecting your X account."
        );
      });
  }, [params, router]);

  return (
    <div className="mx-auto max-w-md py-16">
      <Card className="space-y-3 text-center">
        {status === "working" && (
          <>
            <p className="text-3xl">🤝</p>
            <h1 className="text-xl font-bold text-emerald-900">Connecting your X account…</h1>
            <p className="text-sm text-stone-600">This only takes a moment.</p>
          </>
        )}
        {status === "ok" && (
          <>
            <p className="text-3xl">🎉</p>
            <h1 className="text-xl font-bold text-emerald-900">You are connected!</h1>
            <p className="text-sm text-stone-600">Taking you back to your account…</p>
          </>
        )}
        {status === "error" && (
          <>
            <p className="text-3xl">😕</p>
            <h1 className="text-xl font-bold text-emerald-900">That did not go through</h1>
            <p className="text-sm text-stone-600">{message}</p>
            <a href="/account" className="inline-block text-sm font-medium text-emerald-700 underline">
              Back to your account
            </a>
          </>
        )}
      </Card>
    </div>
  );
}

export default function XCallbackPage() {
  return (
    <Suspense fallback={<p className="text-stone-500">Connecting your X account…</p>}>
      <XCallbackInner />
    </Suspense>
  );
}
