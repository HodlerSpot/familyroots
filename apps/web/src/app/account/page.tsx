"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import JSZip from "jszip";
import { api, ApiError, ensureMediaToken, getToken, mediaUrl, setToken, UserOut } from "@/lib/api";
import { Button, Card, ErrorNote, Label, Modal, PasswordInput } from "@/components/ui";
import { PasswordRules, passwordMeetsRules } from "@/components/password-rules";
import { QuestBoard, testnetApi } from "@/components/testnet/api";
import { Avatar } from "@/components/testnet/identicon";

const IS_TESTNET = process.env.NEXT_PUBLIC_TESTNET === "1";

// Guess a file extension from a content type so media discovered without a
// manifest filename still lands in the zip with a sensible, openable name.
function extFromContentType(contentType: unknown): string {
  if (typeof contentType !== "string") return "";
  const map: Record<string, string> = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "application/pdf": ".pdf",
  };
  return map[contentType] ?? "";
}

// Recursively collect every string that appears under a `media_id` or
// `cloud_media_id` key anywhere in the export bundle, so nested memories,
// capsules, contributions, and legacy media are downloaded too — not just the
// top-level media manifest.
function collectMediaIds(node: unknown, into: Set<string>): void {
  if (Array.isArray(node)) {
    for (const item of node) collectMediaIds(item, into);
    return;
  }
  if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if ((key === "media_id" || key === "cloud_media_id") && typeof value === "string" && value) {
        into.add(value);
      }
      collectMediaIds(value, into);
    }
  }
}

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

  // "Your data" — export download
  const [downloading, setDownloading] = useState(false);
  const [exportError, setExportError] = useState("");

  // "Your data" — delete-account flow (guarded modal)
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteAck, setDeleteAck] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

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

  async function downloadMyData() {
    setExportError("");
    setDownloading(true);
    try {
      const bundle = await api.exportMyData();

      const zip = new JSZip();
      zip.file("futureroots-my-data.json", JSON.stringify(bundle, null, 2));

      // Build the set of media to fetch: start from the top-level manifest
      // (authoritative filenames + content types), then fold in anything
      // referenced deeper in the bundle so nested media come along too.
      const filenames = new Map<string, string>();
      const ids = new Set<string>();
      const manifest = Array.isArray(bundle.media) ? bundle.media : [];
      for (const entry of manifest) {
        if (!entry || typeof entry !== "object") continue;
        const m = entry as { media_id?: unknown; content_type?: unknown; filename?: unknown };
        if (typeof m.media_id !== "string" || !m.media_id) continue;
        ids.add(m.media_id);
        const name =
          typeof m.filename === "string" && m.filename
            ? m.filename
            : m.media_id + extFromContentType(m.content_type);
        filenames.set(m.media_id, name);
      }
      collectMediaIds(bundle, ids);

      // Fetch each file with the short-lived media token. Tolerate per-file
      // failures (network, permission, or the media CORS rule not yet live) so
      // one unreachable file never sinks the whole export — the JSON is already
      // in the zip regardless.
      await ensureMediaToken();
      const unavailable: string[] = [];
      for (const id of ids) {
        const filename = filenames.get(id) ?? id;
        try {
          const res = await fetch(mediaUrl(id));
          if (!res.ok) throw new Error(`couldn't be fetched (HTTP ${res.status})`);
          zip.file(`media/${filename}`, await res.blob());
        } catch (err) {
          unavailable.push(`${id} — ${err instanceof Error ? err.message : "couldn't be fetched"}`);
        }
      }
      if (unavailable.length > 0) {
        zip.file(
          "media/_unavailable.txt",
          "A few of your photos or videos couldn't be added to this download. " +
            "You can still view them in the app, and downloading again later usually picks them up.\n\n" +
            unavailable.join("\n") +
            "\n"
        );
      }

      const blob = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "futureroots-my-data.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(
        err instanceof ApiError
          ? err.message
          : "We couldn't prepare your data just now. Please try again"
      );
    } finally {
      setDownloading(false);
    }
  }

  function openDeleteFlow() {
    setDeletePassword("");
    setDeleteAck(false);
    setDeleteError("");
    setDeleteOpen(true);
  }

  function closeDeleteFlow() {
    if (deleting) return; // don't let a click-away interrupt an in-flight erase
    setDeleteOpen(false);
  }

  async function confirmDelete() {
    if (!deletePassword || !deleteAck || deleting) return;
    setDeleteError("");
    setDeleting(true);
    try {
      await api.deleteMyAccount(deletePassword);
      // Account is gone; clear the session and send them off warmly.
      setToken(null);
      router.replace("/login?farewell=1");
    } catch (err) {
      setDeleting(false);
      if (err instanceof ApiError && err.status === 403) {
        setDeleteError("That password doesn't match. Please try again.");
      } else if (err instanceof ApiError) {
        setDeleteError(err.message);
      } else {
        setDeleteError("We couldn't complete this just now. Please try again.");
      }
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

      {/* --- Your data (GDPR self-serve: export + account deletion) --- */}
      <Card>
        <h2 className="text-lg font-semibold text-emerald-900">Your data</h2>

        {/* Download my data */}
        <div className="mt-4">
          <h3 className="font-medium text-stone-800">Download a copy of your data</h3>
          <p className="mt-1 text-sm text-stone-600">
            Get everything you&apos;ve added to FutureRoots in one zip file: your profile, your
            memories and messages, your contributions, and more — along with your actual photos and
            videos, saved right alongside it.
          </p>
          <div className="mt-3">
            <Button variant="soft" onClick={downloadMyData} disabled={downloading}>
              {downloading ? "Preparing your data…" : "Download my data"}
            </Button>
          </div>
          {exportError && (
            <div className="mt-3">
              <ErrorNote>{exportError}</ErrorNote>
            </div>
          )}
        </div>

        {/* Delete my account */}
        <div className="mt-8 border-t border-stone-200 pt-6">
          <h3 className="font-medium text-stone-800">Delete my account</h3>
          <p className="mt-1 text-sm text-stone-600">
            This permanently closes your account and removes your personal information from
            FutureRoots. This can&apos;t be undone.
          </p>
          <div className="mt-3">
            <Button variant="danger" onClick={openDeleteFlow}>
              Delete my account
            </Button>
          </div>
        </div>
      </Card>

      <DeleteAccountModal
        open={deleteOpen}
        onClose={closeDeleteFlow}
        password={deletePassword}
        onPasswordChange={setDeletePassword}
        ack={deleteAck}
        onAckChange={setDeleteAck}
        deleting={deleting}
        error={deleteError}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function DeleteAccountModal({
  open,
  onClose,
  password,
  onPasswordChange,
  ack,
  onAckChange,
  deleting,
  error,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  password: string;
  onPasswordChange: (v: string) => void;
  ack: boolean;
  onAckChange: (v: boolean) => void;
  deleting: boolean;
  error: string;
  onConfirm: () => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Delete your account">
      <div className="space-y-4">
        <p className="text-stone-700">
          We&apos;re sorry to see you go. Before you confirm, here&apos;s what happens.
        </p>

        <div className="rounded-lg bg-red-50 p-4">
          <p className="text-sm font-medium text-red-900">What we delete</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-red-800">
            <li>Your profile and sign-in</li>
            <li>The memories, messages, and other things you&apos;ve added</li>
            <li>Your notification settings for this account</li>
          </ul>
        </div>

        <div className="rounded-lg bg-stone-100 p-4">
          <p className="text-sm font-medium text-stone-800">What we keep</p>
          <p className="mt-1 text-sm text-stone-600">
            We&apos;re required by law to keep records of payments and contributions. We hold on to
            those financial records, but we remove your name and personal details from them so
            they&apos;re no longer connected to you.
          </p>
        </div>

        <p className="text-sm text-stone-600">
          This is permanent and can&apos;t be undone. To confirm, please re-enter your password.
        </p>

        <div>
          <Label htmlFor="delete-password">Your password</Label>
          <PasswordInput
            id="delete-password"
            value={password}
            onChange={(e) => onPasswordChange(e.target.value)}
            autoComplete="current-password"
            placeholder="Enter your current password"
            disabled={deleting}
          />
        </div>

        <label className="flex cursor-pointer items-start gap-3 text-sm text-stone-700">
          <input
            type="checkbox"
            checked={ack}
            onChange={(e) => onAckChange(e.target.checked)}
            disabled={deleting}
            className="mt-0.5 h-5 w-5 shrink-0 rounded border-stone-300 text-red-600 focus:ring-red-400"
          />
          <span>I understand this permanently deletes my account and can&apos;t be undone.</span>
        </label>

        {error && <ErrorNote>{error}</ErrorNote>}

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="soft" onClick={onClose} disabled={deleting}>
            Keep my account
          </Button>
          <Button
            variant="danger"
            onClick={onConfirm}
            disabled={deleting || !password || !ack}
          >
            {deleting ? "Deleting…" : "Permanently delete"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
