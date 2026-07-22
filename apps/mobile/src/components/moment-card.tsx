// One moment on the family feed: a warm icon + line, any attached photo/video,
// optional extra copy (a milestone's story, a gift's message), the reaction row
// (tap to toggle, optimistic), and a comment button that opens the moment
// detail thread. Mirrors the web feed's MomentCard behavior.
import React, { useState } from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Card, Text, TouchableRipple, useTheme } from "react-native-paper";
import type { FeedEventOut, ReactionSummary } from "@futureroots/types";
import { eventLine } from "@/feed-events";
import { timeAgo } from "@/format";
import { isVideoContentType } from "@/media";
import { api } from "@/api";
import { MediaView } from "./media-view";
import { ReactionBar } from "./reactions";

export function MomentCard({ event }: { event: FeedEventOut }) {
  const router = useRouter();
  const theme = useTheme();
  const { icon, text } = eventLine(event);
  const [reactions, setReactions] = useState<ReactionSummary[]>(event.reactions);

  const p = event.payload;
  const mediaId = p.media_id ? String(p.media_id) : null;
  const isVideo =
    isVideoContentType(p.media_content_type ? String(p.media_content_type) : null) ||
    p.item_type === "video";

  async function toggle(emoji: string) {
    try {
      const res = await api.toggleReaction("feed_event", event.id, emoji);
      setReactions(res.reactions);
    } catch {
      // A failed reaction shouldn't break the feed; leave state as-is.
    }
  }

  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content>
        <View style={styles.headerRow}>
          <Text style={styles.icon}>{icon}</Text>
          <View style={styles.body}>
            <Text variant="bodyLarge" style={styles.text}>
              {text}
            </Text>

            {event.type === "milestone" && p.description ? (
              <Text variant="bodyMedium" style={[styles.muted, { color: theme.colors.onSurfaceVariant }]}>
                {String(p.description)}
              </Text>
            ) : null}

            {(event.type === "contribution" || event.type === "premium_gifted") && p.message ? (
              <Text
                variant="bodyMedium"
                style={[styles.quote, { color: theme.colors.onSurfaceVariant }]}
              >
                “{String(p.message)}”
              </Text>
            ) : null}

            {mediaId ? (
              <View style={styles.media}>
                <MediaView
                  mediaId={mediaId}
                  contentType={isVideo ? "video/*" : String(p.media_content_type ?? "image/*")}
                  accessibilityLabel={String(p.title ?? "family memory")}
                />
              </View>
            ) : null}

            <Text variant="bodySmall" style={[styles.time, { color: theme.colors.onSurfaceVariant }]}>
              {timeAgo(event.created_at)}
            </Text>

            <View style={styles.actions}>
              <ReactionBar reactions={reactions} onToggle={toggle} />
            </View>
          </View>
        </View>
      </Card.Content>

      <TouchableRipple
        onPress={() => router.push(`/moment/${event.id}`)}
        accessibilityRole="button"
        accessibilityLabel={`Comments, ${event.comment_count}`}
        style={styles.commentBar}
      >
        <View style={styles.commentInner}>
          <Text variant="bodyMedium" style={{ color: theme.colors.primary }}>
            💬 {event.comment_count > 0 ? `${event.comment_count} ` : ""}
            {event.comment_count === 1 ? "comment" : "comments"}
          </Text>
          <Text style={{ color: theme.colors.onSurfaceVariant }}>›</Text>
        </View>
      </TouchableRipple>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: 16 },
  headerRow: { flexDirection: "row", gap: 12 },
  icon: { fontSize: 24, lineHeight: 30 },
  body: { flex: 1, minWidth: 0 },
  text: { fontWeight: "500" },
  muted: { marginTop: 4 },
  quote: { marginTop: 4, fontStyle: "italic" },
  media: { marginTop: 12 },
  time: { marginTop: 6 },
  actions: { marginTop: 12 },
  commentBar: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: "rgba(120,113,108,0.25)" },
  commentInner: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 12,
    paddingHorizontal: 16,
  },
});
