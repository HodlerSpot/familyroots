"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";
import { Button, Card } from "@/components/ui";
import { Logo } from "@/components/logo";
import { PixelBackdrop } from "@/components/pixel-backdrop";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    if (getToken()) router.replace("/family");
  }, [router]);

  return (
    <div className="space-y-8 text-center">
      <PixelBackdrop />
      <div className="space-y-5 pt-6">
        <div className="mb-10 flex justify-center">
          <Logo size="lg" withTagline />
        </div>
        <h1 className="text-4xl font-bold text-emerald-900">
          Your family&apos;s story, kept for a lifetime
        </h1>
        <p className="mx-auto max-w-xl text-lg text-stone-600">
          FutureRoots is a private space where your family shares memories, celebrates
          milestones, and builds a future together — for the children you love.
        </p>
      </div>
      <div className="flex justify-center gap-4">
        <Button onClick={() => router.push("/signup")}>Start your family space</Button>
        <Button variant="soft" onClick={() => router.push("/login")}>
          Sign in
        </Button>
      </div>
      <div className="grid gap-4 pt-6 text-left sm:grid-cols-3">
        <Card>
          <h3 className="font-semibold text-emerald-900">Preserve memories</h3>
          <p className="mt-1 text-sm text-stone-600">
            Every child gets a vault of moments, messages, and milestones that stays with
            them for life.
          </p>
        </Card>
        <Card>
          <h3 className="font-semibold text-emerald-900">Bring family close</h3>
          <p className="mt-1 text-sm text-stone-600">
            Grandparents and relatives join in — celebrating achievements the moment they
            happen.
          </p>
        </Card>
        <Card>
          <h3 className="font-semibold text-emerald-900">Grow their future</h3>
          <p className="mt-1 text-sm text-stone-600">
            Turn celebrations into contributions toward the future your children deserve.
          </p>
        </Card>
      </div>
    </div>
  );
}
