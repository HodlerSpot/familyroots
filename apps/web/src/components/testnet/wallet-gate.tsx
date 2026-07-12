"use client";

// The testnet front door: replaces the email login/signup flow with a warm
// wallet-connect screen. Signature-only sign-in on Base Sepolia; there are
// no transactions and nothing to spend.
//
// Wallet choice uses EIP-6963 discovery (wagmi's multiInjectedProviderDiscovery,
// on by default): every installed wallet appears as its own connector with its
// own provider, so picking "MetaMask" reaches MetaMask even when another wallet
// (Temple, Rabby, ...) has claimed window.ethereum.

import { useState } from "react";
import {
  Connector,
  useAccount,
  useConnect,
  useDisconnect,
  useSignMessage,
  useSwitchChain,
} from "wagmi";
import { baseSepolia } from "wagmi/chains";
import { setToken } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";
import { Logo } from "@/components/logo";
import { testnetApi } from "./api";

export function WalletGate({ onSignedIn }: { onSignedIn: () => void }) {
  const { address, isConnected, chainId } = useAccount();
  const { connectors, connectAsync } = useConnect();
  const { disconnect } = useDisconnect();
  const { signMessageAsync } = useSignMessage();
  const { switchChainAsync } = useSwitchChain();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const onBase = chainId === baseSepolia.id;

  // EIP-6963 wallets each carry a distinct id + name + icon. The generic
  // "injected" connector is a catch-all fallback; show it only when no
  // specific wallet was discovered, so users don't see a vague duplicate.
  const discovered = connectors.filter((c) => c.id !== "injected");
  const choices = discovered.length > 0 ? discovered : connectors;

  async function pick(connector: Connector) {
    setError("");
    setPendingId(connector.uid);
    try {
      const result = await connectAsync({ connector });
      // Land the wallet on Base Sepolia so the sign dialog shows the right
      // network (and adds the chain if the wallet doesn't have it yet). The
      // login signature is off-chain, so a failed switch is non-fatal.
      if (result.chainId !== baseSepolia.id) {
        try {
          await switchChainAsync({ chainId: baseSepolia.id });
        } catch {
          // user can still sign; we nudge them below if they're off Base
        }
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "We couldn't reach that wallet. Please try again"
      );
    } finally {
      setPendingId(null);
    }
  }

  async function signIn() {
    if (!address) return;
    setBusy(true);
    setError("");
    try {
      if (!onBase) {
        await switchChainAsync({ chainId: baseSepolia.id });
      }
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

          {!isConnected ? (
            choices.length === 0 ? (
              <p className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
                We couldn&apos;t find a wallet in this browser. Install one (MetaMask and
                Coinbase Wallet both work), then refresh this page.
              </p>
            ) : (
              <div className="space-y-2">
                {choices.map((connector) => (
                  <button
                    key={connector.uid}
                    onClick={() => pick(connector)}
                    disabled={pendingId !== null}
                    className="flex w-full items-center gap-3 rounded-xl border border-stone-200 px-4 py-3 text-left font-semibold text-stone-800 transition-colors hover:border-emerald-400 hover:bg-emerald-50 disabled:opacity-50"
                  >
                    {connector.icon ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={connector.icon} alt="" className="h-7 w-7 rounded-md" />
                    ) : (
                      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-stone-100">
                        👛
                      </span>
                    )}
                    <span className="flex-1">{connector.name}</span>
                    {pendingId === connector.uid && (
                      <span className="text-sm font-normal text-stone-400">Connecting…</span>
                    )}
                  </button>
                ))}
              </div>
            )
          ) : (
            <div className="space-y-3">
              <p className="truncate rounded-lg bg-stone-100 px-4 py-2 text-center font-mono text-sm text-stone-700">
                {address}
              </p>
              {!onBase && (
                <p className="rounded-lg bg-amber-50 px-4 py-2 text-sm text-amber-900">
                  Signing in will switch your wallet to Base Sepolia first.
                </p>
              )}
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
