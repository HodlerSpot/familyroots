"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, setToken } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label, PasswordInput } from "@/components/ui";

function SignupForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/family";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { access_token } = await api.signup(email, name, password);
      setToken(access_token);
      router.push(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong — please try again");
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <h1 className="mb-6 text-2xl font-bold text-emerald-900">Create your account</h1>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <Label htmlFor="name">Your name</Label>
          <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
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
            minLength={8}
            required
          />
          <p className="mt-1 text-xs text-stone-500">At least 8 characters</p>
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating…" : "Create account"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-stone-600">
        Already have an account?{" "}
        <a className="font-medium text-emerald-800 underline" href={`/login?next=${encodeURIComponent(next)}`}>
          Sign in
        </a>
      </p>
    </Card>
  );
}

export default function SignupPage() {
  return (
    <Suspense>
      <SignupForm />
    </Suspense>
  );
}
