"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, getToken, UserOut } from "@/lib/api";
import { Button, Card, ErrorNote, Label, PasswordInput } from "@/components/ui";
import { PasswordRules, passwordMeetsRules } from "@/components/password-rules";

export default function AccountPage() {
  const router = useRouter();
  const [me, setMe] = useState<UserOut | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login?next=/account");
      return;
    }
    api
      .me()
      .then(setMe)
      .catch(() => router.replace("/login?next=/account"));
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await api.changePassword(current, next);
      setSaved(true);
      setCurrent("");
      setNext("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
    } finally {
      setBusy(false);
    }
  }

  if (!me) return <p className="text-stone-500">Loading…</p>;

  return (
    <div className="mx-auto max-w-md space-y-6">
      <div>
        <a href="/family" className="text-sm text-stone-500 underline">
          ← Back to your families
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">Your account</h1>
        <p className="text-stone-600">
          {me.display_name} · {me.email}
        </p>
      </div>

      <Card>
        <h2 className="mb-4 text-lg font-semibold text-emerald-900">Change your password</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label htmlFor="current">Current password</Label>
            <PasswordInput
              id="current"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="new">New password</Label>
            <PasswordInput
              id="new"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
            <PasswordRules password={next} />
          </div>
          {saved && (
            <p className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-900">
              Password updated ✓
            </p>
          )}
          <ErrorNote>{error}</ErrorNote>
          <Button
            type="submit"
            disabled={busy || !passwordMeetsRules(next) || !current}
            className="w-full"
          >
            {busy ? "Saving…" : "Update password"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
