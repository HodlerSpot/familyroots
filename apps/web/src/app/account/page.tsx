"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, getToken, mediaUrl, UserOut } from "@/lib/api";
import { Button, Card, ErrorNote, Label, PasswordInput } from "@/components/ui";
import { PasswordRules, passwordMeetsRules } from "@/components/password-rules";
import { QuestBoard, testnetApi } from "@/components/testnet/api";
import { Avatar } from "@/components/testnet/identicon";

const IS_TESTNET = process.env.NEXT_PUBLIC_TESTNET === "1";

export default function AccountPage() {
  return IS_TESTNET ? <TestnetAccount /> : <FamilyAccount />;
}

// --- Wallet-based tester account (testnet only) ---

function shortWallet(addr: string): string {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

function TestnetAccount() {
  const router = useRouter();
  const [board, setBoard] = useState<QuestBoard | null>(null);
  const [name, setName] = useState("");
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [xBusy, setXBusy] = useState(false);
  const [xUnavailable, setXUnavailable] = useState(false);
  const [xError, setXError] = useState("");
  const [disconnecting, setDisconnecting] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login?next=/account");
      return;
    }
    testnetApi
      .quests()
      .then((b) => {
        setBoard(b);
        setName(b.display_name ?? "");
      })
      .catch(() => router.replace("/login?next=/account"));
  }, [router]);

  async function saveName(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await testnetApi.setProfile(name.trim());
      setSaved(true);
      setBoard((b) => (b ? { ...b, display_name: name.trim() } : b));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again");
    } finally {
      setBusy(false);
    }
  }

  function copyWallet() {
    if (!board) return;
    navigator.clipboard?.writeText(board.wallet_address);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function connectX() {
    setXBusy(true);
    setXError("");
    try {
      const { authorize_url } = await testnetApi.xStart();
      window.location.assign(authorize_url);
    } catch (err) {
      // A 503 means X isn't set up on this deployment: hide the button. Any
      // other failure is transient, so surface a gentle retry message.
      const message = err instanceof Error ? err.message : "";
      if (message.includes("isn't set up")) {
        setXUnavailable(true);
      } else {
        setXError("We couldn't reach X just now. Please try again");
      }
      setXBusy(false);
    }
  }

  async function disconnectX() {
    setDisconnecting(true);
    setXError("");
    try {
      await testnetApi.xDisconnect();
      setBoard((b) => (b ? { ...b, x_username: null, avatar_url: null } : b));
    } catch {
      setXError("We couldn't disconnect just now. Please try again");
    } finally {
      setDisconnecting(false);
    }
  }

  if (!board) return <p className="text-stone-500">Loading…</p>;

  return (
    <div className="mx-auto max-w-md space-y-6">
      <div>
        <a href="/family" className="text-sm text-stone-500 underline">
          Back to testing
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">Your tester account</h1>
      </div>

      <Card className="space-y-5">
        <div className="flex items-center gap-4">
          <Avatar seed={board.wallet_address} src={board.avatar_url} size={64} />
          <div className="min-w-0">
            <p className="text-lg font-bold text-stone-900">
              {board.x_username || board.display_name || shortWallet(board.wallet_address)}
            </p>
            <button
              onClick={copyWallet}
              className="mt-0.5 font-mono text-sm text-stone-500 hover:text-stone-700"
              title="Copy full address"
            >
              {shortWallet(board.wallet_address)}
              <span className="ml-2 text-xs">{copied ? "copied ✓" : "copy"}</span>
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between rounded-xl bg-emerald-50 px-4 py-3">
          <span className="text-sm font-medium text-emerald-900">Points earned</span>
          <span className="text-2xl font-extrabold tabular-nums text-emerald-900">
            {board.total_points}
          </span>
        </div>
        <a
          href="/leaderboard"
          className="block text-center text-sm font-medium text-emerald-700 underline"
        >
          See the leaderboard
        </a>
      </Card>

      {!xUnavailable && (
        <Card>
          <h2 className="mb-1 text-lg font-semibold text-emerald-900">Bring your crew</h2>
          {board.x_username ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-stone-900">{board.x_username}</p>
                  <p className="text-sm text-stone-600">
                    Your X picture and handle show on the leaderboard.
                  </p>
                </div>
                <span className="shrink-0 rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-800">
                  Connected ✓
                </span>
              </div>
              <button
                onClick={disconnectX}
                disabled={disconnecting}
                className="text-sm text-stone-500 underline hover:text-stone-700 disabled:opacity-50"
              >
                {disconnecting ? "Disconnecting…" : "Disconnect X"}
              </button>
              <ErrorNote>{xError}</ErrorNote>
            </div>
          ) : (
            <>
              <p className="mb-4 text-sm text-stone-600">
                Connect your X account to swap your identicon for your real profile picture
                and @handle. It is worth 100 points, and it is easy to undo later.
              </p>
              <Button onClick={connectX} disabled={xBusy} className="w-full">
                {xBusy ? "Opening X…" : "Connect X"}
              </Button>
              <ErrorNote>{xError}</ErrorNote>
            </>
          )}
        </Card>
      )}

      {!board.x_username && (
      <Card>
        <h2 className="mb-1 text-lg font-semibold text-emerald-900">Leaderboard name</h2>
        <p className="mb-4 text-sm text-stone-600">
          Choose how you appear to other testers. Leave it blank to stay a shortened wallet.
        </p>
        <form onSubmit={saveName} className="space-y-4">
          <div>
            <Label htmlFor="name">Display name</Label>
            <input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={40}
              placeholder={shortWallet(board.wallet_address)}
              className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base text-stone-900 placeholder-stone-400 focus:border-emerald-600 focus:outline-none"
            />
          </div>
          {saved && (
            <p className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-900">
              Saved ✓
            </p>
          )}
          <ErrorNote>{error}</ErrorNote>
          <Button type="submit" disabled={busy || !name.trim()} className="w-full">
            {busy ? "Saving…" : "Save name"}
          </Button>
        </form>
      </Card>
      )}
    </div>
  );
}

// --- Email/password family account (the product) ---

function FamilyAccount() {
  const router = useRouter();
  const [me, setMe] = useState<UserOut | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState("");
  const [photoSaved, setPhotoSaved] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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

  async function onPickPhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setPhotoBusy(true);
    setPhotoError("");
    setPhotoSaved(false);
    try {
      const updated = await api.uploadMyAvatar(file);
      setMe(updated);
      setPhotoSaved(true);
    } catch (err) {
      setPhotoError(
        err instanceof ApiError ? err.message : "We couldn't save that photo. Please try again."
      );
    } finally {
      setPhotoBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

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
          Back to your families
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">Your account</h1>
        <p className="text-stone-600">
          {me.display_name} · {me.email}
        </p>
      </div>

      <Card>
        <h2 className="text-lg font-semibold text-emerald-900">Profile photo</h2>
        <p className="mt-1 text-sm text-stone-600">
          Add a photo of yourself. When your camera is off on a family call, the family will see
          this instead.
        </p>

        <div className="mt-5 flex items-center gap-4">
          {me.avatar_media_id ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl(me.avatar_media_id)}
              alt="Your profile photo"
              className="h-20 w-20 rounded-full object-cover"
            />
          ) : (
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-100 text-2xl font-semibold text-emerald-800">
              {(me.display_name ?? "?").charAt(0).toUpperCase()}
            </div>
          )}
          <div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              onChange={onPickPhoto}
              disabled={photoBusy}
              className="hidden"
              id="avatar-input"
            />
            <Button
              type="button"
              variant="soft"
              onClick={() => fileRef.current?.click()}
              disabled={photoBusy}
            >
              {photoBusy ? "Saving…" : me.avatar_media_id ? "Change photo" : "Add a photo"}
            </Button>
            {photoSaved && (
              <p className="mt-2 text-sm font-medium text-emerald-700" aria-live="polite">
                Looking great. Your photo is saved.
              </p>
            )}
          </div>
        </div>

        {photoError && (
          <div className="mt-4">
            <ErrorNote>{photoError}</ErrorNote>
          </div>
        )}
      </Card>

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
