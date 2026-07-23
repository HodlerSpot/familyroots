// The in-call screen: a full-screen, dark, immersive takeover (the one dark
// surface in FutureRoots, matching the web FamilyCallLayer). It owns the whole
// react-native-agora lifecycle for one member's presence in the call:
//
//   join  -> prime camera/mic, create + initialize the engine, subscribe to
//            everyone, publish whatever tracks we were allowed
//   live  -> adaptive video grid with the active speaker pinned first, presence
//            chips for the little ones in the room, three large controls
//   keep  -> heartbeat every 10s, roster poll every 5s, renew the token before
//            it expires, keep the screen awake
//   leave -> gentle confirm, then tear the engine down and tell the API
//
// Nothing here blocks on a missing camera or mic: the member joins with a warm
// banner and can still see and hear everyone (mirrors the web fallbacks).
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Modal, Pressable, ScrollView, StatusBar, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { ActivityIndicator, Button, Dialog, Portal, Text } from "react-native-paper";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useKeepAwake } from "expo-keep-awake";
import {
  ChannelProfileType,
  ClientRoleType,
  ConnectionStateType,
  RemoteVideoState,
  createAgoraRtcEngine,
  type IRtcEngine,
  type IRtcEngineEventHandler,
} from "react-native-agora";
import type { CallJoin, CallState } from "@futureroots/types";
import { api } from "@/api";
import { emerald, red, stone } from "@futureroots/tokens";
import {
  formatElapsed,
  mediaFallbackNote,
  primeCallPermissions,
  type CallPermissions,
} from "@/call";
import { ParticipantTile, type CallTile } from "./participant-tile";

const MAX_TILES = 9;
const HEARTBEAT_MS = 10_000;
const ROSTER_POLL_MS = 5_000;
const VOLUME_INTERVAL_MS = 400;
// Renew the token this far ahead of its epoch-seconds expiry, as a backstop to
// the SDK's own onTokenPrivilegeWillExpire callback.
const TOKEN_REFRESH_LEAD_MS = 30_000;
const SPEAKING_THRESHOLD = 15; // volume is 0-255; low bar so a soft voice pins.

type Status = "connecting" | "connected" | "reconnecting" | "ended";

interface RemoteState {
  uid: number;
  cameraOn: boolean;
  muted: boolean;
}

export function InCallScreen({
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
  useKeepAwake();

  const engineRef = useRef<IRtcEngine | null>(null);
  const handlerRef = useRef<IRtcEngineEventHandler | null>(null);
  const cleanedUp = useRef(false);
  const tokenTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [status, setStatus] = useState<Status>("connecting");
  const [perms, setPerms] = useState<CallPermissions>({ camera: false, mic: false });
  const [micOn, setMicOn] = useState(false);
  const [camOn, setCamOn] = useState(false);
  const [remotes, setRemotes] = useState<RemoteState[]>([]);
  const [activeSpeaker, setActiveSpeaker] = useState<number | null>(null);
  const [roster, setRoster] = useState<CallState>(join.call);
  const [elapsed, setElapsed] = useState(0);
  const [leaveConfirm, setLeaveConfirm] = useState(false);

  const localUid = join.agora_uid;

  // --- token refresh (shared by the SDK callback and the backstop timer) ---
  const renewToken = useCallback(async () => {
    try {
      const t = await api.refreshCallToken(familyId);
      engineRef.current?.renewToken(t.token);
      scheduleTokenRefresh(t.expires_at);
    } catch {
      // If it truly lapses the SDK surfaces a reconnect; nothing to do here.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [familyId]);

  const scheduleTokenRefresh = useCallback(
    (expiresAtEpochSeconds: number) => {
      if (tokenTimer.current) clearTimeout(tokenTimer.current);
      const ms = expiresAtEpochSeconds * 1000 - Date.now() - TOKEN_REFRESH_LEAD_MS;
      tokenTimer.current = setTimeout(() => void renewToken(), Math.max(0, ms));
    },
    [renewToken]
  );

  // --- teardown (idempotent): used by Leave and on unmount ---
  const teardown = useCallback(async () => {
    if (cleanedUp.current) return;
    cleanedUp.current = true;
    if (tokenTimer.current) clearTimeout(tokenTimer.current);
    const engine = engineRef.current;
    try {
      engine?.stopPreview();
    } catch {
      /* not previewing */
    }
    try {
      engine?.leaveChannel();
    } catch {
      /* not in a channel */
    }
    try {
      if (handlerRef.current) engine?.unregisterEventHandler(handlerRef.current);
      engine?.release();
    } catch {
      /* already released */
    }
    engineRef.current = null;
    try {
      await api.leaveCall(familyId);
    } catch {
      /* best effort */
    }
  }, [familyId]);

  // --- Agora lifecycle: prime, init, join, publish, wire events ---
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const granted = await primeCallPermissions();
      if (cancelled) return;
      setPerms(granted);
      setMicOn(granted.mic);
      setCamOn(granted.camera);

      const engine = createAgoraRtcEngine();
      engineRef.current = engine;
      engine.initialize({ appId: join.app_id });

      const handler: IRtcEngineEventHandler = {
        onJoinChannelSuccess: () => {
          if (!cancelled) setStatus("connected");
        },
        onUserJoined: (_c, remoteUid) => {
          setRemotes((prev) =>
            prev.some((r) => r.uid === remoteUid)
              ? prev
              : [...prev, { uid: remoteUid, cameraOn: false, muted: false }]
          );
        },
        onUserOffline: (_c, remoteUid) => {
          setRemotes((prev) => prev.filter((r) => r.uid !== remoteUid));
        },
        onRemoteVideoStateChanged: (_c, remoteUid, state) => {
          const on = state !== RemoteVideoState.RemoteVideoStateStopped;
          setRemotes((prev) =>
            prev.map((r) => (r.uid === remoteUid ? { ...r, cameraOn: on } : r))
          );
        },
        onUserMuteAudio: (_c, remoteUid, muted) => {
          setRemotes((prev) =>
            prev.map((r) => (r.uid === remoteUid ? { ...r, muted } : r))
          );
        },
        onAudioVolumeIndication: (_c, speakers) => {
          let top: number | null = null;
          let max = 0;
          for (const s of speakers) {
            const vol = s.volume ?? 0;
            if (vol > max) {
              max = vol;
              // uid 0 in a volume report is the local user.
              top = s.uid && s.uid !== 0 ? s.uid : localUid;
            }
          }
          setActiveSpeaker(max > SPEAKING_THRESHOLD ? top : null);
        },
        onConnectionStateChanged: (_c, state) => {
          if (cleanedUp.current) return;
          if (state === ConnectionStateType.ConnectionStateReconnecting) {
            setStatus("reconnecting");
          } else if (state === ConnectionStateType.ConnectionStateConnected) {
            setStatus("connected");
          }
        },
        onTokenPrivilegeWillExpire: () => {
          void renewToken();
        },
        onError: () => {
          // Transient SDK errors are common (device busy, brief network); the
          // connection-state callbacks drive the user-visible status instead.
        },
      };
      handlerRef.current = handler;
      engine.registerEventHandler(handler);

      // Enable video so we can always SEE others; only preview our own camera
      // when we were granted it.
      engine.enableVideo();
      if (granted.camera) engine.startPreview();
      engine.enableAudioVolumeIndication(VOLUME_INTERVAL_MS, 3, false);

      engine.joinChannel(join.token, join.channel_name, localUid, {
        clientRoleType: ClientRoleType.ClientRoleBroadcaster,
        channelProfile: ChannelProfileType.ChannelProfileCommunication,
        publishMicrophoneTrack: granted.mic,
        publishCameraTrack: granted.camera,
        autoSubscribeAudio: true,
        autoSubscribeVideo: true,
      });

      scheduleTokenRefresh(join.expires_at);
    })();

    return () => {
      cancelled = true;
      void teardown();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- heartbeat ---
  useEffect(() => {
    const id = setInterval(() => void api.callHeartbeat(familyId).catch(() => {}), HEARTBEAT_MS);
    return () => clearInterval(id);
  }, [familyId]);

  // --- roster poll (names / avatars / children present) ---
  useEffect(() => {
    let stopped = false;
    const id = setInterval(async () => {
      try {
        const s = await api.callState(familyId);
        if (!stopped) setRoster(s);
      } catch {
        /* keep last roster */
      }
    }, ROSTER_POLL_MS);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, [familyId]);

  // --- live elapsed timer ---
  useEffect(() => {
    const startedAt = roster.started_at ?? join.call.started_at;
    if (!startedAt) return;
    const start = new Date(startedAt).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [roster.started_at, join.call.started_at]);

  async function toggleMic() {
    if (!perms.mic) return;
    const next = !micOn;
    engineRef.current?.muteLocalAudioStream(!next);
    setMicOn(next);
  }

  function toggleCam() {
    if (!perms.camera) return;
    const next = !camOn;
    const engine = engineRef.current;
    engine?.enableLocalVideo(next);
    engine?.muteLocalVideoStream(!next);
    if (next) engine?.startPreview();
    else engine?.stopPreview();
    setCamOn(next);
  }

  async function doLeave() {
    await teardown();
    onClose();
  }

  // --- build tiles: local first, then remotes, active speaker pinned ---
  const tiles = useMemo<CallTile[]>(() => {
    const byUid = new Map(roster.participants.map((p) => [p.agora_uid, p]));
    const me = byUid.get(localUid);
    const local: CallTile = {
      key: "local",
      uid: 0,
      name: me?.display_name ?? "You",
      avatarMediaId: me?.avatar_media_id ?? null,
      cameraOn: camOn,
      muted: !micOn,
      isLocal: true,
      isYou: true,
      speaking: activeSpeaker === localUid,
    };
    const remoteTiles: CallTile[] = remotes.map((r) => {
      const p = byUid.get(r.uid);
      return {
        key: String(r.uid),
        uid: r.uid,
        name: p?.display_name ?? "Family",
        avatarMediaId: p?.avatar_media_id ?? null,
        cameraOn: r.cameraOn,
        muted: r.muted,
        speaking: activeSpeaker === r.uid,
      };
    });
    const all = [local, ...remoteTiles];
    all.sort((a, b) => Number(!!b.speaking) - Number(!!a.speaking));
    return all;
  }, [roster.participants, remotes, camOn, micOn, activeSpeaker, localUid]);

  const overflow = Math.max(0, tiles.length - MAX_TILES);
  const visible = overflow > 0 ? tiles.slice(0, MAX_TILES - 1) : tiles;
  const cellWidth = visible.length + (overflow > 0 ? 1 : 0) <= 1 ? "100%" : "48%";
  const fallbackNote = mediaFallbackNote(perms);
  const aloneOnCall = status === "connected" && remotes.length === 0;
  const childrenPresent = roster.children_present;

  return (
    <Modal
      visible
      animationType="fade"
      statusBarTranslucent
      presentationStyle="fullScreen"
      onRequestClose={() => setLeaveConfirm(true)}
    >
      <StatusBar barStyle="light-content" />
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        {/* Top bar */}
        <View style={styles.header}>
          <View style={styles.headerText}>
            <Text variant="titleMedium" style={styles.headerTitle} numberOfLines={1}>
              {familyName} family call
            </Text>
            <Text variant="bodySmall" style={styles.headerSub}>
              {status === "reconnecting"
                ? "Reconnecting..."
                : status === "connecting"
                  ? "Live now"
                  : elapsed > 0
                    ? `Everyone's been here ${formatElapsed(elapsed)}`
                    : "Live now"}
            </Text>
          </View>
          <Pressable
            onPress={() => setLeaveConfirm(true)}
            style={styles.leavePill}
            accessibilityRole="button"
            accessibilityLabel="Leave the call"
          >
            <Text style={styles.leavePillText}>Leave</Text>
          </Pressable>
        </View>

        {/* Warm banners */}
        {status === "reconnecting" ? (
          <Banner tone="amber">Reconnecting you to the family. Hang tight...</Banner>
        ) : null}
        {fallbackNote ? <Banner tone="stone">{fallbackNote}</Banner> : null}

        {/* Grid */}
        {status === "connecting" ? (
          <View style={styles.centerFill}>
            <ActivityIndicator color={emerald[400]} size="large" />
            <Text style={styles.centerText}>Just a moment, gathering the family...</Text>
          </View>
        ) : status === "ended" ? (
          <View style={styles.centerFill}>
            <Text style={styles.endedText}>This family call has ended.</Text>
            <Button mode="contained" onPress={onClose}>
              Back to the family
            </Button>
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.gridScroll}>
            {aloneOnCall ? (
              <View style={styles.aloneNote}>
                <Text style={styles.aloneText}>
                  You're the first one here. We'll show everyone as they join.
                </Text>
              </View>
            ) : null}
            <View style={styles.grid}>
              {visible.map((t) => (
                <View key={t.key} style={{ width: cellWidth }}>
                  <ParticipantTile data={t} />
                </View>
              ))}
              {overflow > 0 ? (
                <View style={[styles.overflowTile, { width: cellWidth }]}>
                  <Text style={styles.overflowText}>+{overflow + 1} more here</Text>
                </View>
              ) : null}
            </View>
          </ScrollView>
        )}

        {/* Presence strip: little ones in the room */}
        {childrenPresent.length > 0 ? (
          <View style={styles.presenceRow}>
            <Text style={styles.presenceLabel}>Here in the room</Text>
            {childrenPresent.map((c) => (
              <View key={c.child_id} style={styles.presenceChip}>
                <Text style={styles.presenceChipText}>{c.first_name}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* Control bar: three large (56pt) labeled controls */}
        <View style={styles.controls}>
          <ControlButton
            icon={micOn ? "microphone" : "microphone-off"}
            label={micOn ? "Mute" : "Unmute"}
            onPress={toggleMic}
            disabled={!perms.mic}
            active={micOn}
          />
          <ControlButton
            icon={camOn ? "video" : "video-off"}
            label={camOn ? "Camera on" : "Camera off"}
            onPress={toggleCam}
            disabled={!perms.camera}
            active={camOn}
          />
          <ControlButton icon="phone-hangup" label="Leave" onPress={() => setLeaveConfirm(true)} danger />
        </View>

        <Portal>
          <Dialog visible={leaveConfirm} onDismiss={() => setLeaveConfirm(false)}>
            <Dialog.Title>Leave the family call?</Dialog.Title>
            <Dialog.Content>
              <Text variant="bodyMedium">
                Everyone else can keep talking. You can always join again from the family page.
              </Text>
            </Dialog.Content>
            <Dialog.Actions>
              <Button onPress={() => setLeaveConfirm(false)}>Stay on the call</Button>
              <Button onPress={doLeave} textColor={red[600]}>
                Yes, leave
              </Button>
            </Dialog.Actions>
          </Dialog>
        </Portal>
      </SafeAreaView>
    </Modal>
  );
}

function ControlButton({
  icon,
  label,
  onPress,
  disabled,
  active,
  danger,
}: {
  icon: React.ComponentProps<typeof MaterialCommunityIcons>["name"];
  label: string;
  onPress: () => void;
  disabled?: boolean;
  active?: boolean;
  danger?: boolean;
}) {
  const bg = danger ? red[600] : active ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.28)";
  return (
    <View style={styles.control}>
      <Pressable
        onPress={onPress}
        disabled={disabled}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ disabled: !!disabled, selected: !!active }}
        style={[styles.controlButton, { backgroundColor: bg, opacity: disabled ? 0.4 : 1 }]}
      >
        <MaterialCommunityIcons name={icon} size={28} color="#ffffff" />
      </Pressable>
      <Text style={styles.controlLabel}>{label}</Text>
    </View>
  );
}

function Banner({ tone, children }: { tone: "amber" | "stone"; children: React.ReactNode }) {
  return (
    <View style={[styles.banner, tone === "amber" ? styles.bannerAmber : styles.bannerStone]}>
      <Text style={styles.bannerText}>{children}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: stone[900] },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "rgba(255,255,255,0.12)",
    gap: 12,
  },
  headerText: { flex: 1, minWidth: 0 },
  headerTitle: { color: "#ffffff", fontWeight: "700" },
  headerSub: { color: "rgba(255,255,255,0.6)" },
  leavePill: {
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.12)",
    paddingHorizontal: 18,
    paddingVertical: 10,
  },
  leavePillText: { color: "#ffffff", fontWeight: "700" },
  banner: { paddingHorizontal: 16, paddingVertical: 8 },
  bannerAmber: { backgroundColor: "rgba(245,158,11,0.2)" },
  bannerStone: { backgroundColor: "rgba(255,255,255,0.06)" },
  bannerText: { color: "#f5f5f4", textAlign: "center" },
  centerFill: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16, padding: 24 },
  centerText: { color: "rgba(255,255,255,0.9)", fontSize: 17, textAlign: "center" },
  endedText: { color: "#ffffff", fontSize: 20, fontWeight: "700", textAlign: "center" },
  gridScroll: { padding: 12, gap: 12 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12, justifyContent: "center" },
  aloneNote: {
    alignSelf: "center",
    maxWidth: 460,
    borderRadius: 16,
    backgroundColor: "rgba(255,255,255,0.06)",
    paddingHorizontal: 20,
    paddingVertical: 12,
    marginBottom: 4,
  },
  aloneText: { color: "rgba(255,255,255,0.8)", textAlign: "center" },
  overflowTile: {
    aspectRatio: 3 / 4,
    borderRadius: 20,
    backgroundColor: stone[800],
    alignItems: "center",
    justifyContent: "center",
  },
  overflowText: { color: "rgba(255,255,255,0.8)", fontSize: 17, fontWeight: "700" },
  presenceRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "rgba(255,255,255,0.12)",
  },
  presenceLabel: {
    color: "rgba(255,255,255,0.5)",
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  presenceChip: {
    borderRadius: 999,
    backgroundColor: "rgba(16,185,129,0.2)",
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  presenceChipText: { color: emerald[100], fontSize: 13, fontWeight: "600" },
  controls: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 28,
    paddingVertical: 16,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "rgba(255,255,255,0.12)",
  },
  control: { alignItems: "center", gap: 6 },
  controlButton: {
    width: 64,
    height: 64,
    minWidth: 56,
    minHeight: 56,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  controlLabel: { color: "#ffffff", fontSize: 13, fontWeight: "600" },
});
