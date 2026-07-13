"use client";

import { useEffect, useRef } from "react";
import type { ILocalVideoTrack, IRemoteVideoTrack } from "agora-rtc-sdk-ng";
import { mediaUrl } from "@/lib/api";

export interface TileData {
  key: string;
  name: string;
  avatarMediaId: string | null;
  videoTrack?: ILocalVideoTrack | IRemoteVideoTrack;
  cameraOn: boolean;
  muted: boolean;
  isLocal?: boolean;
  isYou?: boolean;
  speaking?: boolean;
}

function initial(name: string) {
  return name.trim().charAt(0).toUpperCase() || "?";
}

export function ParticipantTile({
  data,
  className = "",
}: {
  data: TileData;
  className?: string;
}) {
  const { name, avatarMediaId, videoTrack, cameraOn, muted, isLocal, isYou, speaking } = data;
  const videoRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = videoRef.current;
    if (!el || !videoTrack || !cameraOn) return;
    try {
      videoTrack.play(el, { fit: "cover", mirror: !!isLocal });
    } catch {
      // Track may have been closed mid-render; ignore.
    }
    return () => {
      try {
        videoTrack.stop();
      } catch {
        // already stopped
      }
    };
  }, [videoTrack, cameraOn, isLocal]);

  const showVideo = cameraOn && !!videoTrack;
  const speakingRing = speaking ? "ring-4 ring-emerald-400" : "ring-1 ring-white/10";

  return (
    <div
      className={`relative aspect-video w-full overflow-hidden rounded-2xl bg-stone-800 shadow-lg transition ${speakingRing} ${className}`}
    >
      {/* Live video (hidden, not unmounted, so the track keeps flowing under a camera-off overlay) */}
      <div
        ref={videoRef}
        className={`absolute inset-0 h-full w-full ${showVideo ? "opacity-100" : "opacity-0"}`}
      />

      {/* Camera-off warm tile */}
      {!showVideo && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-gradient-to-br from-amber-100 to-emerald-50">
          {avatarMediaId ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl(avatarMediaId)}
              alt=""
              className="h-20 w-20 rounded-full object-cover shadow-sm sm:h-24 sm:w-24"
            />
          ) : (
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-200 text-3xl font-semibold text-emerald-800 sm:h-24 sm:w-24">
              {initial(name)}
            </div>
          )}
          <p className="px-3 text-center text-lg font-semibold text-emerald-900">{name}</p>
        </div>
      )}

      {/* Name pill (over video) */}
      {showVideo && (
        <div className="absolute bottom-2 left-2 rounded-full bg-stone-900/60 px-3 py-1 text-sm font-medium text-white">
          {name}
          {isYou && <span className="text-white/70"> (you)</span>}
        </div>
      )}

      {/* Badges */}
      <div className="absolute right-2 top-2 flex gap-1.5">
        {muted && (
          <span
            className="flex items-center gap-1 rounded-full bg-stone-900/70 px-2 py-1 text-xs font-medium text-white"
            title="Microphone off"
          >
            <MicOffIcon />
            <span className="sr-only">Microphone off</span>
          </span>
        )}
        {!cameraOn && (
          <span
            className="flex items-center gap-1 rounded-full bg-stone-900/70 px-2 py-1 text-xs font-medium text-white"
            title="Camera off"
          >
            <CamOffIcon />
            <span className="sr-only">Camera off</span>
          </span>
        )}
      </div>
    </div>
  );
}

function MicOffIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="1" y1="1" x2="23" y2="23" />
      <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6" />
      <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23" />
      <line x1="12" y1="19" x2="12" y2="23" />
    </svg>
  );
}

function CamOffIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <line x1="1" y1="1" x2="23" y2="23" />
      <path d="M16 16H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2m4-2h4a2 2 0 0 1 2 2v6l4-4v8" />
    </svg>
  );
}
