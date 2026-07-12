"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, getToken, InvitePreview } from "@/lib/api";
import { familyPhrase } from "@/lib/text";
import { Button, Card, ErrorNote } from "@/components/ui";

export default function InvitePage() {
  const router = useRouter();
  const { token } = useParams<{ token: string }>();
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .previewInvite(token)
      .then(setPreview)
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 410
            ? "This invitation has expired or was already used. Ask your family member to send a new one."
            : "We couldn't find this invitation."
        )
      );
  }, [token]);

  async function accept() {
    if (!getToken()) {
      router.push(`/signup?next=${encodeURIComponent(`/invites/${token}`)}`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const family = await api.acceptInvite(token);
      router.push(`/family/${family.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  if (error && !preview) return <ErrorNote>{error}</ErrorNote>;
  if (!preview) return <p className="text-stone-500">Loading…</p>;

  return (
    <Card className="mx-auto max-w-lg space-y-6 text-center">
      <div className="text-5xl">💌</div>
      <h1 className="text-2xl font-bold text-emerald-900">
        {preview.invited_by} invited you to join {familyPhrase(preview.family_name)}
      </h1>
      <p className="text-stone-600">
        You&apos;re joining as a <span className="font-semibold capitalize">{preview.role}</span> in
        a private space where your family shares memories, celebrates milestones, and
        builds a future together.
      </p>
      <ErrorNote>{error}</ErrorNote>
      <Button onClick={accept} disabled={busy} className="w-full">
        {busy ? "Joining…" : "Join your family"}
      </Button>
      {!getToken() && (
        <p className="text-sm text-stone-500">
          You&apos;ll create your account first. It takes less than a minute.
        </p>
      )}
    </Card>
  );
}
