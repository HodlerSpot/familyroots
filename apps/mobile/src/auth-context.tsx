// App-wide authentication state for the native app.
//
// Owns a single status machine (loading -> authed | unauthed) hydrated from
// SecureStore at boot, exposes sign-in/sign-out, and — crucially — registers
// the api-client's onSessionExpired hook so a 401 anywhere flips the app back
// to the auth stack without any window.location (there is none on native).
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, client, setSessionExpiredHandler } from "./api";
import { hydrateSession } from "./session-store";

export type AuthStatus = "loading" | "authed" | "unauthed";

interface AuthContextValue {
  status: AuthStatus;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");

  useEffect(() => {
    let active = true;
    // A lapsed session (any authenticated 401) drops us to the login stack.
    setSessionExpiredHandler(() => {
      if (active) setStatus("unauthed");
    });
    void hydrateSession().then(() => {
      if (active) setStatus(client.getToken() ? "authed" : "unauthed");
    });
    return () => {
      active = false;
      setSessionExpiredHandler(null);
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      async signIn(email: string, password: string) {
        // Native sessions are always "stay logged in" (remember = true).
        const res = await api.login(email, password, true);
        client.setToken(res.access_token, { remember: true });
        setStatus("authed");
      },
      async signUp(name: string, email: string, password: string) {
        // Create the account, then land straight in the app on the returned
        // token. Like sign-in, native accounts are always remembered.
        const res = await api.signup(email, name, password);
        client.setToken(res.access_token, { remember: true });
        setStatus("authed");
      },
      signOut() {
        client.setToken(null);
        setStatus("unauthed");
      },
    }),
    [status]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
