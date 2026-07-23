// Active-family context: the app is scoped to ONE family at a time.
//
// Mirrors the web app's family gating, but where the web has a families list
// page the native shell keeps a single "active family" (persisted in
// SecureStore) and swaps it from a switcher sheet in the Home header. The tab
// set and affordances are computed from the active family's ROLE — supporters
// get the reduced surface (mirror of web `isSupporter`: no Add, no Legacy, no
// Fund internals, no call).
//
// Families are fetched once via the shared api and cached by TanStack Query so
// every screen reads the same list. The active id is validated against that
// list on load (a stale persisted id falls back to the first family).
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as SecureStore from "expo-secure-store";
import { useQuery } from "@tanstack/react-query";
import type { FamilySummary } from "@futureroots/types";
import { api } from "./api";

const ACTIVE_KEY = "futureroots.activeFamilyId";

interface ActiveFamilyContextValue {
  /** All families the signed-in member belongs to (never null once loaded). */
  families: FamilySummary[];
  /** The currently active family, or null while loading / when none exist. */
  activeFamily: FamilySummary | null;
  /** Switch the active family (persisted). Ignores unknown ids. */
  setActiveFamilyId: (id: string) => void;
  /** Make a family active without the membership guard, for the moment right
   * after joining via an invite (the families list may still be refetching). */
  activateFamily: (id: string) => void;
  /** True when the active family's role is supporter (reduced surface). */
  isSupporter: boolean;
  loading: boolean;
  error: boolean;
  refetch: () => void;
}

const ActiveFamilyContext = createContext<ActiveFamilyContextValue | null>(null);

export function ActiveFamilyProvider({ children }: { children: ReactNode }) {
  const {
    data: families,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["families"],
    queryFn: () => api.myFamilies(),
  });

  const [activeId, setActiveId] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  // Load the persisted active id once at boot.
  useEffect(() => {
    let active = true;
    void SecureStore.getItemAsync(ACTIVE_KEY)
      .catch(() => null)
      .then((id) => {
        if (active) {
          setActiveId(id);
          setHydrated(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  // Once families load, reconcile the active id: keep it if still a member,
  // otherwise fall back to the first family. Persist any correction.
  useEffect(() => {
    if (!hydrated || !families) return;
    const stillValid = activeId && families.some((f) => f.id === activeId);
    if (stillValid) return;
    const next = families[0]?.id ?? null;
    setActiveId(next);
    if (next) void SecureStore.setItemAsync(ACTIVE_KEY, next).catch(() => {});
  }, [hydrated, families, activeId]);

  function setActiveFamilyId(id: string) {
    if (!families?.some((f) => f.id === id)) return;
    setActiveId(id);
    void SecureStore.setItemAsync(ACTIVE_KEY, id).catch(() => {});
  }

  function activateFamily(id: string) {
    setActiveId(id);
    void SecureStore.setItemAsync(ACTIVE_KEY, id).catch(() => {});
  }

  const activeFamily = useMemo(
    () => families?.find((f) => f.id === activeId) ?? null,
    [families, activeId]
  );

  const value = useMemo<ActiveFamilyContextValue>(
    () => ({
      families: families ?? [],
      activeFamily,
      setActiveFamilyId,
      activateFamily,
      isSupporter: activeFamily?.role === "supporter",
      loading: isLoading || !hydrated,
      error: isError,
      refetch: () => void refetch(),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [families, activeFamily, isLoading, hydrated, isError]
  );

  return <ActiveFamilyContext.Provider value={value}>{children}</ActiveFamilyContext.Provider>;
}

export function useActiveFamily(): ActiveFamilyContextValue {
  const ctx = useContext(ActiveFamilyContext);
  if (!ctx) throw new Error("useActiveFamily must be used within an ActiveFamilyProvider");
  return ctx;
}
