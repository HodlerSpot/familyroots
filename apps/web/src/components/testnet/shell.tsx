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
        <div className="bg-gradient-to-r from-[#1FA84D] to-[#1E4FD8] px-4 py-2 text-center text-xs font-semibold text-white sm:text-sm">
          🎮 FutureRoots Testing Crew · rack up points as you explore · rewards for top testers coming soon 🎁
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
