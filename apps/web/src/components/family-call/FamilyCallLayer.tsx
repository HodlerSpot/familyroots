"use client";

import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  IAgoraRTCClient,
  IAgoraRTCRemoteUser,
  ICameraVideoTrack,
  ILocalTrack,
  IMicrophoneAudioTrack,
} from "agora-rtc-sdk-ng";
import { api, CallJoin, CallState, mediaUrl } from "@/lib/api";
import { Button, Modal } from "@/components/ui";
import { ParticipantTile, TileData } from "./ParticipantTile";

const MAX_VISIBLE = 9;
const FOCUSABLE =
  'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])';

type Status = "connecting" | "connected" | "reconnecting" | "ended";

export function FamilyCallLayer({
  familyId,
  familyName,
  join,
  onClose,
}: {
  familyId: string;
  familyName: string;
  join: CallJoin;
  onClose: () => void;
}) {
  const clientRef = useRef<IAgoraRTCClient | null>(null);
  const localAudioRef = useRef<IMicrophoneAudioTrack | null>(null);
  const localVideoRef = useRef<ICameraVideoTrack | null>(null);
  const cleanedUp = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const muteBtnRef = useRef<HTMLButtonElement>(null);

  const [localVideoTrack, setLocalVideoTrack] = useState<ICameraVideoTrack | null>(null);
  const [remoteUsers, setRemoteUsers] = useState<IAgoraRTCRemoteUser[]>([]);
  const [roster, setRoster] = useState<CallState>(join.call);
  const [status, setStatus] = useState<Status>("connecting");
  const [micOn, setMicOn] = useState(true);
  const [camOn, setCamOn] = useState(true);
  const [mediaWarning, setMediaWarning] = useState("");
  const [activeSpeaker, setActiveSpeaker] = useState<number | null>(null);
  const [leaveConfirm, setLeaveConfirm] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  // --- portal host + make the rest of the page inert while the call is open ---
  const [host] = useState(() => (typeof document !== "undefined" ? document.createElement("div") : null));
  useEffect(() => {
    if (!host) return;
    document.body.appendChild(host);
    const siblings = Array.from(document.body.children).filter((c) => c !== host);
    siblings.forEach((c) => {
      c.setAttribute("inert", "");
      c.setAttribute("aria-hidden", "true");
    });
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      siblings.forEach((c) => {
        c.removeAttribute("inert");
        c.removeAttribute("aria-hidden");
      });
      document.body.style.overflow = prevOverflow;
      if (host.parentNode) host.parentNode.removeChild(host);
    };
  }, [host]);

  // --- teardown (idempotent): used by Leave and on unmount ---
  const teardown = useCallback(async () => {
    if (cleanedUp.current) return;
    cleanedUp.current = true;
    try {
      localVideoRef.current?.close();
    } catch {
      /* already closed */
    }
    try {
      localAudioRef.current?.close();
    } catch {
      /* already closed */
    }
    try {
      await clientRef.current?.leave();
    } catch {
      /* not connected */
    }
    try {
      await api.leaveCall(familyId);
    } catch {
      /* best effort */
    }
  }, [familyId]);

  // --- Agora lifecycle: join, publish, wire events (dynamic import only) ---
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const AgoraRTC = (await import("agora-rtc-sdk-ng")).default;
      const client = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
      clientRef.current = client;

      const syncRemotes = () => setRemoteUsers([...client.remoteUsers]);

      client.on("user-published", async (user, mediaType) => {
        try {
          await client.subscribe(user, mediaType);
        } catch {
          /* subscribe race; will retry on next publish */
        }
        if (mediaType === "audio") {
          try {
            user.audioTrack?.play();
          } catch {
            /* ignore */
          }
        }
        syncRemotes();
      });
      client.on("user-unpublished", syncRemotes);
      client.on("user-joined", syncRemotes);
      client.on("user-left", syncRemotes);

      client.on("connection-state-change", (cur) => {
        if (cleanedUp.current) return;
        if (cur === "RECONNECTING") setStatus("reconnecting");
        else if (cur === "CONNECTED") setStatus("connected");
      });

      client.on("token-privilege-will-expire", async () => {
        try {
          const t = await api.refreshCallToken(familyId);
          await client.renewToken(t.token);
        } catch {
          /* will surface as a reconnect if it truly expires */
        }
      });

      client.enableAudioVolumeIndicator();
      client.on("volume-indicator", (volumes) => {
        let top: number | null = null;
        let max = 0;
        for (const v of volumes) {
          if (v.level > max) {
            max = v.level;
            top = Number(v.uid) === 0 ? join.agora_uid : Number(v.uid);
          }
        }
        setActiveSpeaker(max > 5 ? top : null);
      });

      try {
        await client.join(join.app_id, join.channel_name, join.token, join.agora_uid);
      } catch {
        if (!cancelled) setStatus("ended");
        return;
      }
      if (cancelled) return;

      // Never block joining on a missing camera or mic.
      let mic: IMicrophoneAudioTrack | null = null;
      let cam: ICameraVideoTrack | null = null;
      try {
        [mic, cam] = await AgoraRTC.createMicrophoneAndCameraTracks();
      } catch {
        try {
          mic = await AgoraRTC.createMicrophoneAudioTrack();
          setMediaWarning(
            "We couldn't reach your camera, so you've joined with just your voice. Everyone can still hear you."
          );
        } catch {
          setMediaWarning(
            "We couldn't reach your camera or microphone. You can still see and hear everyone here."
          );
        }
      }
      if (cancelled) {
        mic?.close();
        cam?.close();
        return;
      }

      localAudioRef.current = mic;
      localVideoRef.current = cam;
      setLocalVideoTrack(cam);
      setMicOn(!!mic);
      setCamOn(!!cam);

      const pubs: ILocalTrack[] = [];
      if (mic) pubs.push(mic);
      if (cam) pubs.push(cam);
      if (pubs.length) {
        try {
          await client.publish(pubs);
        } catch {
          /* publish can be retried by SDK on reconnect */
        }
      }

      if (!cancelled) setStatus("connected");
    })();

    return () => {
      cancelled = true;
      void teardown();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- roster poll (names / avatars / children present) every 5s ---
  useEffect(() => {
    let stopped = false;
    const poll = async () => {
      try {
        const s = await api.callState(familyId);
        if (!stopped) setRoster(s);
      } catch {
        /* keep last roster */
      }
    };
    const id = setInterval(poll, 5000);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, [familyId]);

  // --- heartbeat every 10s ---
  useEffect(() => {
    const id = setInterval(() => {
      void api.callHeartbeat(familyId).catch(() => {});
    }, 10000);
    return () => clearInterval(id);
  }, [familyId]);

  // --- live timer ---
  useEffect(() => {
    const startedAt = roster.started_at ?? join.call.started_at;
    if (!startedAt) return;
    const start = new Date(startedAt).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [roster.started_at, join.call.started_at]);

  // --- focus starts on Mute ---
  useEffect(() => {
    const t = setTimeout(() => muteBtnRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, []);

  async function toggleMic() {
    const t = localAudioRef.current;
    if (!t) return;
    const next = !micOn;
    try {
      await t.setEnabled(next);
      setMicOn(next);
    } catch {
      /* device busy */
    }
  }

  async function toggleCam() {
    const t = localVideoRef.current;
    if (!t) return;
    const next = !camOn;
    try {
      await t.setEnabled(next);
      setCamOn(next);
    } catch {
      /* device busy */
    }
  }

  async function doLeave() {
    await teardown();
    onClose();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      // Esc never leaves instantly; it opens the gentle confirm.
      if (!leaveConfirm) {
        e.preventDefault();
        setLeaveConfirm(true);
      }
      return;
    }
    if (e.key !== "Tab" || !containerRef.current) return;
    const nodes = containerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
    if (nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // --- build tiles from local + remote, mapped to the roster for names ---
  const tiles = useMemo<TileData[]>(() => {
    const meP =
      roster.participants.find((p) => p.is_you) ??
      roster.participants.find((p) => p.agora_uid === join.agora_uid);
    const localTile: TileData = {
      key: "local",
      name: meP?.display_name ?? "You",
      avatarMediaId: meP?.avatar_media_id ?? null,
      videoTrack: localVideoTrack ?? undefined,
      cameraOn: camOn,
      muted: !micOn,
      isLocal: true,
      isYou: true,
      speaking: activeSpeaker === join.agora_uid,
    };
    const remoteTiles: TileData[] = remoteUsers.map((u) => {
      const uid = Number(u.uid);
      const p = roster.participants.find((pp) => pp.agora_uid === uid);
      return {
        key: String(u.uid),
        name: p?.display_name ?? "Family",
        avatarMediaId: p?.avatar_media_id ?? null,
        videoTrack: u.videoTrack,
        cameraOn: !!u.hasVideo,
        muted: !u.hasAudio,
        speaking: activeSpeaker === uid,
      };
    });
    const all = [localTile, ...remoteTiles];
    // On a phone the active speaker is pinned to the top of the stack.
    all.sort((a, b) => Number(!!b.speaking) - Number(!!a.speaking));
    return all;
  }, [roster.participants, remoteUsers, localVideoTrack, camOn, micOn, activeSpeaker, join.agora_uid]);

  const overflow = Math.max(0, tiles.length - MAX_VISIBLE);
  const visibleTiles = overflow > 0 ? tiles.slice(0, MAX_VISIBLE - 1) : tiles;
  const gridCols = colsFor(visibleTiles.length + (overflow > 0 ? 1 : 0));
  const aloneOnCall = status === "connected" && remoteUsers.length === 0;

  const content = (
    <div
      ref={containerRef}
      role="dialog"
      aria-modal="true"
      aria-label={`Family call with the ${familyName} family`}
      onKeyDown={onKeyDown}
      className="fixed inset-0 z-40 flex flex-col bg-stone-900 text-white"
    >
      {/* Top bar */}
      <header className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden
            className="h-2.5 w-2.5 shrink-0 rounded-full bg-amber-400 motion-safe:animate-pulse"
          />
          <div className="min-w-0">
            <p className="truncate text-base font-semibold">{familyName} family call</p>
            <p className="text-xs text-white/60" aria-live="off">
              {status === "reconnecting"
                ? "Reconnecting…"
                : elapsed > 0
                  ? `Everyone's been here ${formatElapsed(elapsed)}`
                  : "Live now"}
            </p>
          </div>
        </div>
        <button
          onClick={() => setLeaveConfirm(true)}
          className="rounded-full bg-white/10 px-4 py-2 text-sm font-semibold text-white hover:bg-white/20"
        >
          Leave
        </button>
      </header>

      {/* Warm status banners */}
      {status === "reconnecting" && (
        <Banner tone="amber">Reconnecting you to the family. Hang tight…</Banner>
      )}
      {mediaWarning && <Banner tone="stone">{mediaWarning}</Banner>}

      {/* Participant grid */}
      <main className="flex-1 overflow-y-auto p-4">
        {status === "connecting" ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <Spinner />
            <p className="text-lg font-medium text-white/90">Just a moment, gathering the family…</p>
          </div>
        ) : status === "ended" ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <p className="text-xl font-semibold">This family call has ended.</p>
            <Button onClick={onClose}>Back to the family</Button>
          </div>
        ) : (
          <>
            {aloneOnCall && (
              <div className="mx-auto mb-4 max-w-lg rounded-2xl bg-white/5 px-5 py-3 text-center text-sm text-white/80">
                You&apos;re the first one here. We&apos;ll show everyone as they join.
              </div>
            )}
            <div className={`mx-auto grid gap-4 ${gridCols}`}>
              {visibleTiles.map((t) => (
                <ParticipantTile key={t.key} data={t} />
              ))}
              {overflow > 0 && (
                <div className="flex aspect-video w-full items-center justify-center rounded-2xl bg-stone-800 text-lg font-semibold text-white/80">
                  +{overflow + 1} more here
                </div>
              )}
            </div>
          </>
        )}
      </main>

      {/* Presence strip: little ones in the room */}
      {roster.children_present.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-white/10 px-4 py-2">
          <span className="text-xs font-medium uppercase tracking-wide text-white/50">
            Here in the room
          </span>
          {roster.children_present.map((c) => (
            <span
              key={c.child_id}
              className="flex items-center gap-1.5 rounded-full bg-emerald-500/20 py-1 pl-1 pr-3 text-sm text-emerald-100"
            >
              {c.avatar_media_id ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={mediaUrl(c.avatar_media_id)}
                  alt=""
                  className="h-6 w-6 rounded-full object-cover"
                />
              ) : (
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-400/40 text-xs font-semibold">
                  {c.first_name.charAt(0).toUpperCase()}
                </span>
              )}
              {c.first_name}
            </span>
          ))}
        </div>
      )}

      {/* Control bar */}
      <footer className="flex items-center justify-center gap-4 border-t border-white/10 px-4 py-4">
        <ControlButton
          ref={muteBtnRef}
          onClick={toggleMic}
          pressed={!micOn}
          disabled={!localAudioRef.current}
          label={micOn ? "Turn microphone off" : "Turn microphone on"}
          icon={micOn ? <MicIcon /> : <MicOffIcon />}
          active={micOn}
        />
        <ControlButton
          onClick={toggleCam}
          pressed={!camOn}
          disabled={!localVideoRef.current}
          label={camOn ? "Turn camera off" : "Turn camera on"}
          icon={camOn ? <CamIcon /> : <CamOffIcon />}
          active={camOn}
        />
        <ControlButton
          onClick={() => setLeaveConfirm(true)}
          label="Leave the call"
          icon={<LeaveIcon />}
          danger
        />
      </footer>

      <Modal
        open={leaveConfirm}
        onClose={() => setLeaveConfirm(false)}
        title="Leave the family call?"
      >
        <p className="-mt-2 mb-5 text-sm text-stone-600">
          Everyone else can keep talking. You can always join again from the family page.
        </p>
        <div className="flex flex-col gap-2">
          <Button variant="danger" onClick={doLeave}>
            Yes, leave the call
          </Button>
          <Button variant="soft" onClick={() => setLeaveConfirm(false)}>
            Stay on the call
          </Button>
        </div>
      </Modal>
    </div>
  );

  if (!host) return null;
  return createPortal(content, host);
}

function colsFor(n: number): string {
  if (n <= 1) return "grid-cols-1 max-w-3xl";
  if (n <= 2) return "grid-cols-1 sm:grid-cols-2 max-w-5xl";
  if (n <= 4) return "grid-cols-1 sm:grid-cols-2 max-w-5xl";
  return "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 max-w-6xl";
}

function formatElapsed(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

function Banner({ tone, children }: { tone: "amber" | "stone"; children: React.ReactNode }) {
  const cls = tone === "amber" ? "bg-amber-500/20 text-amber-100" : "bg-white/5 text-white/80";
  return (
    <div role="status" className={`px-4 py-2 text-center text-sm ${cls}`}>
      {children}
    </div>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="h-10 w-10 rounded-full border-4 border-white/20 border-t-emerald-400 motion-safe:animate-spin"
    />
  );
}

const ControlButton = forwardRef<
  HTMLButtonElement,
  {
    onClick: () => void;
    label: string;
    icon: React.ReactNode;
    pressed?: boolean;
    active?: boolean;
    danger?: boolean;
    disabled?: boolean;
  }
>(function ControlButton({ onClick, label, icon, pressed, active, danger, disabled }, ref) {
  const base =
    "flex h-14 w-14 min-h-[56px] min-w-[56px] flex-col items-center justify-center rounded-2xl text-white transition disabled:opacity-40 sm:h-16 sm:w-20";
  const tone = danger
    ? "bg-red-600 hover:bg-red-700"
    : active
      ? "bg-white/15 hover:bg-white/25"
      : "bg-white/25 hover:bg-white/35";
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={`${base} ${tone}`}
    >
      {icon}
    </button>
  );
});

function MicIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
    </svg>
  );
}
function MicOffIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="1" y1="1" x2="23" y2="23" />
      <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6" />
      <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23" />
      <line x1="12" y1="19" x2="12" y2="23" />
    </svg>
  );
}
function CamIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M23 7l-7 5 7 5V7z" />
      <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
    </svg>
  );
}
function CamOffIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="1" y1="1" x2="23" y2="23" />
      <path d="M16 16H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2m4-2h4a2 2 0 0 1 2 2v6l4-4v8" />
    </svg>
  );
}
function LeaveIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M18.36 6.64a9 9 0 1 1-12.73 0" />
      <line x1="12" y1="2" x2="12" y2="12" />
    </svg>
  );
}
