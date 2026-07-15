"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, getToken } from "@/lib/api";
import { Button, Card } from "@/components/ui";
import { goToFundSetup } from "@/components/fund";

/**
 * Stripe sends people here when their setup link has expired mid-flow.
 * We quietly mint a fresh link and send them straight back in.
 */
export default function FundSetupRefreshPage() {
  const router = useRouter();
  const { id: familyId, childId } = useParams<{ id: string; childId: string }>();
  const [childName, setChildName] = useState("");
  const [failed, setFailed] = useState(false);

  const vaultPath = `/family/${familyId}/child/${childId}`;

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    api
      .familyDetail(familyId)
      .then((family) => {
        setChildName(family.children.find((c) => c.id === childId)?.first_name ?? "");
      })
      .catch(() => {
        // Name is a nicety; the redirect below is what matters.
      });
    goToFundSetup(childId).catch(() => setFailed(true));
  }, [familyId, childId, router]);

  if (failed) {
    return (
      <Card className="mx-auto max-w-lg space-y-4 text-center">
        <p className="text-stone-600">
          That link went stale. Start again from {childName ? `${childName}'s` : "the"} vault.
        </p>
        <Button variant="soft" className="w-full" onClick={() => router.push(vaultPath)}>
          Back to {childName ? `${childName}'s` : "the"} vault
        </Button>
      </Card>
    );
  }

  return <p className="text-center text-stone-500">One moment…</p>;
}
