"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, setToken } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label, PasswordInput } from "@/components/ui";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/family";
  const timedOut = params.get("reason") === "timeout";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { access_token } = await api.login(email, password, remember);
      setToken(access_token, { remember });
      router.push(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="mb-6 text-2xl font-bold text-emerald-900">Welcome back</h1>
      {timedOut && (
        <p className="mb-6 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Your session timed out to keep your family&apos;s space safe. Please sign in
          again to pick up where you left off.
        </p>
      )}
      <form onSubmit={submit} className="space-y-4">
        <div>
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div>
          <Label htmlFor="password">Password</Label>
          <PasswordInput
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <label className="flex items-center gap-3 text-sm text-stone-700">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            className="h-5 w-5 rounded border-stone-300 text-emerald-700 focus:ring-emerald-500"
          />
          Stay logged in on this device
        </label>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-3 text-center text-sm">
        <a className="text-stone-500 underline" href="/forgot-password">
          Forgot your password?
        </a>
      </p>
      <p className="mt-3 text-center text-sm text-stone-600">
        New to FutureRoots?{" "}
        <a className="font-medium text-emerald-800 underline" href={`/signup?next=${encodeURIComponent(next)}`}>
          Create an account
        </a>
      </p>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
