"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Button, Card, ErrorNote, Label, PasswordInput } from "@/components/ui";
import { PasswordRules, passwordMeetsRules } from "@/components/password-rules";

export default function ResetPasswordPage() {
  const router = useRouter();
  const { token } = useParams<{ token: string }>();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Card className="mx-auto max-w-md space-y-3 text-center">
        <div className="text-4xl">✅</div>
        <h1 className="text-2xl font-bold text-emerald-900">Password updated</h1>
        <p className="text-stone-600">You can sign in with your new password now.</p>
        <Button onClick={() => router.push("/login")} className="w-full">
          Sign in
        </Button>
      </Card>
    );
  }

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="mb-6 text-2xl font-bold text-emerald-900">Choose a new password</h1>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <Label htmlFor="password">New password</Label>
          <PasswordInput
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <PasswordRules password={password} />
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button
          type="submit"
          disabled={busy || !passwordMeetsRules(password)}
          className="w-full"
        >
          {busy ? "Saving…" : "Set new password"}
        </Button>
      </form>
    </Card>
  );
}
