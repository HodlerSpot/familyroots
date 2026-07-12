"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <Card className="mx-auto max-w-md space-y-3 text-center">
        <div className="text-4xl">📬</div>
        <h1 className="text-2xl font-bold text-emerald-900">Check your email</h1>
        <p className="text-stone-600">
          If an account exists for <span className="font-medium">{email}</span>, a reset
          link is on its way. It works once and expires in an hour.
        </p>
        <p className="text-sm text-stone-500">
          Nothing arriving? Check your spam folder, or{" "}
          <a href="/forgot-password" className="underline" onClick={() => setSent(false)}>
            try again
          </a>
          .
        </p>
      </Card>
    );
  }

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="mb-2 text-2xl font-bold text-emerald-900">Reset your password</h1>
      <p className="mb-6 text-sm text-stone-600">
        Enter your email and we&apos;ll send you a link to choose a new one.
      </p>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Sending…" : "Send reset link"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-stone-600">
        <a className="underline" href="/login">
          Back to sign in
        </a>
      </p>
    </Card>
  );
}
