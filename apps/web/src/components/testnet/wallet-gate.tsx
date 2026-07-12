"use client";

// The testnet front door: replaces the email login/signup flow with a warm
// wallet-connect screen. Signature-only sign-in on Base Sepolia; there are
// no transactions and nothing to spend.

import { useState } from "react";
import { useAccount, useConnect, useDisconnect, useSignMessage } from "wagmi";
import { setToken } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";
import { Logo } from "@/components/logo";
import { testnetApi } from "./api";

export function WalletGate({ onSignedIn }: { onSignedIn: () => void }) {
  const { address, isConnected } = useAccount();
  const { connect, connectors, isPending: connecting } = useConnect();
  const { disconnect } = useDisconnect();
  const { signMessageAsync } = useSignMessage();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const connector = connectors[0];

  async function signIn() {
    if (!address) return;
    setBusy(true);
    setError("");
    try {
      const { message } = await testnetApi.nonce(address);
      const signature = await signMessageAsync({ message });
      const { access_token } = await testnetApi.verify(address, signature);
      setToken(access_token);
      onSignedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <div className="space-y-8 text-center">
        <div className="flex justify-center pt-6">
          <Logo size="lg" withTagline />
        </div>
        <div className="space-y-3">
          <h1 className="text-3xl font-bold text-emerald-900">
            Welcome to the FutureRoots testing crew
          </h1>
          <p className="mx-auto max-w-xl text-lg text-stone-600">
            Help us make family memories unbreakable. Try real flows, earn points for
            every corner you explore, and climb the tester leaderboard.
          </p>
        </div>
        <Card className="mx-auto max-w-md text-left">
          <h2 className="mb-2 text-lg font-semibold text-emerald-900">
            Connect your wallet to start testing
          </h2>
          <p className="mb-5 text-sm text-stone-600">
            Your wallet is only your tester sign-in on Base Sepolia. You sign one
            message to prove it&apos;s yours. No transactions, no fees, nothing to spend.
          </p>
          {!connector ? (
            <p className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
              We couldn&apos;t find a wallet in this browser. Install one (MetaMask or
              Coinbase Wallet both work), then refresh this page.
            </p>
          ) : !isConnected ? (
            <Button
              className="w-full"
              disabled={connecting}
              onClick={() => connect({ connector })}
            >
              {connecting ? "Connecting…" : "Connect wallet"}
            </Button>
          ) : (
            <div className="space-y-3">
              <p className="truncate rounded-lg bg-stone-100 px-4 py-2 text-center font-mono text-sm text-stone-700">
                {address}
              </p>
              <Button className="w-full" disabled={busy} onClick={signIn}>
                {busy ? "Signing you in…" : "Sign in and start testing"}
              </Button>
              <button
                type="button"
                className="w-full text-center text-sm text-stone-500 underline"
                onClick={() => disconnect()}
              >
                Use a different wallet
              </button>
            </div>
          )}
          <ErrorNote>{error}</ErrorNote>
        </Card>
        <p className="text-sm text-stone-500">
          Every action you test helps real families keep their memories safe. Thank you
          for being here.
        </p>
      </div>
    </main>
  );
}
