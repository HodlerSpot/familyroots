// One person's tile in the in-call grid. Renders their live video with Agora's
// native RtcSurfaceView when their camera is on, and a warm avatar tile when it
// is off (or before their stream arrives). The active speaker gets an emerald
// ring, mirroring the web ParticipantTile.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";
import { RtcSurfaceView, RenderModeType, VideoSourceType } from "react-native-agora";
import { emerald, stone } from "@futureroots/tokens";
import { Avatar } from "@/components/avatar";

export interface CallTile {
  key: string;
  /** Agora uid to render. 0 = the local user. */
  uid: number;
  name: string;
  avatarMediaId: string | null;
  cameraOn: boolean;
  muted: boolean;
  isLocal?: boolean;
  isYou?: boolean;
  speaking?: boolean;
}

export function ParticipantTile({ data }: { data: CallTile }) {
  const { uid, name, avatarMediaId, cameraOn, muted, isLocal, isYou, speaking } = data;

  return (
    <View style={[styles.tile, speaking ? styles.speaking : styles.idle]}>
      {cameraOn ? (
        <RtcSurfaceView
          style={styles.video}
          canvas={{
            uid,
            renderMode: RenderModeType.RenderModeHidden,
            // The local preview reads from the primary camera source.
            sourceType: isLocal ? VideoSourceType.VideoSourceCamera : undefined,
          }}
          zOrderMediaOverlay={!isLocal}
        />
      ) : (
        <View style={styles.off}>
          <Avatar name={name} mediaId={avatarMediaId} size={84} />
          <Text variant="titleMedium" style={styles.offName}>
            {name}
            {isYou ? " (you)" : ""}
          </Text>
        </View>
      )}

      {/* Name pill (over live video) */}
      {cameraOn ? (
        <View style={styles.namePill}>
          <Text style={styles.namePillText}>
            {name}
            {isYou ? " (you)" : ""}
          </Text>
        </View>
      ) : null}

      {/* Muted badge */}
      {muted ? (
        <View style={styles.mutedBadge} accessibilityLabel={`${name} has their microphone off`}>
          <Text style={styles.mutedText}>Muted</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  tile: {
    width: "100%",
    aspectRatio: 3 / 4,
    borderRadius: 20,
    overflow: "hidden",
    backgroundColor: stone[800],
    borderWidth: 3,
  },
  idle: { borderColor: "rgba(255,255,255,0.08)" },
  speaking: { borderColor: emerald[400] },
  video: { flex: 1 },
  off: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    backgroundColor: stone[800],
  },
  offName: { color: "#ffffff", fontWeight: "700", textAlign: "center", paddingHorizontal: 8 },
  namePill: {
    position: "absolute",
    left: 8,
    bottom: 8,
    borderRadius: 999,
    backgroundColor: "rgba(28,25,23,0.66)",
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  namePillText: { color: "#ffffff", fontSize: 13, fontWeight: "600" },
  mutedBadge: {
    position: "absolute",
    right: 8,
    top: 8,
    borderRadius: 999,
    backgroundColor: "rgba(28,25,23,0.75)",
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  mutedText: { color: "#ffffff", fontSize: 12, fontWeight: "600" },
});
