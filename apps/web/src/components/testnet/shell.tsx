"use client";

// Testnet shell: mounts the wallet providers, shows the harness banner, and
// gates the whole app behind wallet sign-in. Loaded only via dynamic import
// from TestnetRoot when NEXT_PUBLIC_TESTNET=1 (see docs/testnet.md).

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WagmiProvider, createConfig, http } from "wagmi";
import { baseSepolia } from "wagmi/chains";
import { injected } from "wagmi/connectors";
import { getToken } from "@/lib/api";
import { WalletGate } from "./wallet-gate";
import { QuestsButton } from "./quests";

const config = createConfig({
  chains: [baseSepolia],
  connectors: [injected()],
  transports: { [baseSepolia.id]: http() },
});

const queryClient = new QueryClient();

export default function TestnetShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // null until mounted: the token lives in localStorage, client-side only
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    setAuthed(Boolean(getToken()));
  }, [pathname]);

  return (
    <WagmiProvider config={config}>
      <QueryClientProvider client={queryClient}>
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-center text-xs font-semibold tracking-wide text-amber-900">
          FutureRoots Testnet · points mode
        </div>
        {authed === null ? null : authed ? (
          <>
            {children}
            <QuestsButton />
          </>
        ) : (
          <WalletGate onSignedIn={() => setAuthed(true)} />
        )}
      </QueryClientProvider>
    </WagmiProvider>
  );
}
