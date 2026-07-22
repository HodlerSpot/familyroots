// Moment detail: the full moment (icon, line, media, reactions) plus its
// comment thread. Comments can be reacted to and posted (both working writes,
// mirroring the web feed); a comment you're allowed to remove shows a delete
// action. The parent moment is read from the shared feed query cache.
import React, { useMemo, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { useLocalSearchParams } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Divider,
  HelperText,
  IconButton,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { useQuery } from "@tanstack/react-query";
import type { CommentOut, FeedEventOut, ReactionSummary } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { eventLine } from "@/feed-events";
import { timeAgo } from "@/format";
import { isVideoContentType } from "@/media";
import { api } from "@/api";
import { useActiveFamily } from "@/active-family";
import { MediaView } from "@/components/media-view";
import { ReactionBar } from "@/components/reactions";

export default function MomentDetailScreen() {
  const theme = useTheme();
  const { eventId } = useLocalSearchParams<{ eventId: string }>();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;

  // The moment itself comes from the feed list (cached from Home/Feed). When we
  // arrive without that cache we refetch the feed and pick it out.
  const feed = useQuery({
    queryKey: ["feed", familyId],
    queryFn: () => api.familyFeed(familyId as string),
    enabled: !!familyId,
  });
  const event = useMemo(
    () => feed.data?.find((e) => e.id === eventId) ?? null,
    [feed.data, eventId]
  );

  const comments = useQuery({
    queryKey: ["comments", eventId],
    queryFn: () => api.listComments(eventId),
    enabled: !!eventId,
  });

  const [reactions, setReactions] = useState<ReactionSummary[] | null>(null);
  const [thread, setThread] = useState<CommentOut[] | null>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState("");

  // Seed local editable copies once the server data lands.
  const liveReactions = reactions ?? event?.reactions ?? [];
  const liveThread = thread ?? comments.data ?? [];

  async function toggleMoment(emoji: string) {
    try {
      const res = await api.toggleReaction("feed_event", eventId, emoji);
      setReactions(res.reactions);
    } catch {
      // ignore; keep current reactions
    }
  }

  async function toggleComment(comment: CommentOut, emoji: string) {
    try {
      const { reactions: next } = await api.toggleReaction("comment", comment.id, emoji);
      setThread((prev) =>
        (prev ?? comments.data ?? []).map((c) =>
          c.id === comment.id ? { ...c, reactions: next } : c
        )
      );
    } catch {
      // ignore
    }
  }

  async function removeComment(comment: CommentOut) {
    try {
      await api.deleteComment(comment.id);
      setThread((prev) => (prev ?? comments.data ?? []).filter((c) => c.id !== comment.id));
    } catch {
      // ignore
    }
  }

  async function submit() {
    const body = draft.trim();
    if (!body) return;
    setPosting(true);
    setError("");
    try {
      const created = await api.addComment(eventId, body);
      setThread((prev) => [...(prev ?? comments.data ?? []), created]);
      setDraft("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't post your comment");
    } finally {
      setPosting(false);
    }
  }

  if (feed.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  const line: { icon: string; text: string } = event
    ? eventLine(event)
    : { icon: "✨", text: "This moment" };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={90}
    >
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={comments.isRefetching}
            onRefresh={() => {
              setThread(null);
              void comments.refetch();
            }}
          />
        }
      >
        {/* The moment */}
        <Card mode="outlined" style={styles.card}>
          <Card.Content>
            <View style={styles.headerRow}>
              <Text style={styles.icon}>{line.icon}</Text>
              <View style={styles.body}>
                <Text variant="bodyLarge" style={styles.text}>
                  {line.text}
                </Text>
                {event?.type === "milestone" && event.payload.description ? (
                  <Text
                    variant="bodyMedium"
                    style={[styles.muted, { color: theme.colors.onSurfaceVariant }]}
                  >
                    {String(event.payload.description)}
                  </Text>
                ) : null}
                {event &&
                (event.type === "contribution" || event.type === "premium_gifted") &&
                event.payload.message ? (
                  <Text
                    variant="bodyMedium"
                    style={[styles.quote, { color: theme.colors.onSurfaceVariant }]}
                  >
                    “{String(event.payload.message)}”
                  </Text>
                ) : null}
                {event?.payload.media_id ? (
                  <View style={styles.media}>
                    <MediaView
                      mediaId={String(event.payload.media_id)}
                      contentType={
                        isVideoContentType(String(event.payload.media_content_type ?? "")) ||
                        event.payload.item_type === "video"
                          ? "video/*"
                          : String(event.payload.media_content_type ?? "image/*")
                      }
                    />
                  </View>
                ) : null}
                {event ? (
                  <Text
                    variant="bodySmall"
                    style={[styles.time, { color: theme.colors.onSurfaceVariant }]}
                  >
                    {timeAgo(event.created_at)}
                  </Text>
                ) : null}
                <View style={styles.actions}>
                  <ReactionBar reactions={liveReactions} onToggle={toggleMoment} />
                </View>
              </View>
            </View>
          </Card.Content>
        </Card>

        {/* Comments */}
        <Text variant="titleMedium" style={styles.threadTitle}>
          Comments
        </Text>

        {comments.isLoading ? (
          <ActivityIndicator style={styles.loading} />
        ) : liveThread.length === 0 ? (
          <Text style={{ color: theme.colors.onSurfaceVariant }}>
            Be the first to say something kind.
          </Text>
        ) : (
          <View style={styles.commentList}>
            {liveThread.map((c) => (
              <Card
                key={c.id}
                mode="contained"
                style={[styles.comment, { backgroundColor: theme.colors.surfaceVariant }]}
              >
                <Card.Content>
                  <View style={styles.commentHead}>
                    <Text variant="labelLarge" style={styles.author}>
                      {c.author_name}
                    </Text>
                    <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                      {timeAgo(c.created_at)}
                    </Text>
                  </View>
                  <Text variant="bodyMedium" style={styles.commentBody}>
                    {c.body}
                  </Text>
                  <View style={styles.commentActions}>
                    <ReactionBar reactions={c.reactions} onToggle={(e) => toggleComment(c, e)} size="sm" />
                    {c.can_delete ? (
                      <IconButton
                        icon="trash-can-outline"
                        size={18}
                        onPress={() => removeComment(c)}
                        accessibilityLabel="Delete comment"
                        style={styles.deleteBtn}
                      />
                    ) : null}
                  </View>
                </Card.Content>
              </Card>
            ))}
          </View>
        )}

        <Divider style={styles.divider} />

        {/* Add a comment (working write) */}
        <TextInput
          mode="outlined"
          label="Add a comment"
          value={draft}
          onChangeText={setDraft}
          multiline
          style={styles.input}
        />
        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}
        <Button
          mode="contained"
          onPress={submit}
          disabled={posting || !draft.trim()}
          loading={posting}
          style={styles.submit}
        >
          Post comment
        </Button>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 12 },
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
  threadTitle: { fontWeight: "700", marginTop: 4 },
  loading: { marginTop: 12 },
  commentList: { gap: 8 },
  comment: { borderRadius: 12 },
  commentHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  author: { fontWeight: "700" },
  commentBody: { marginTop: 2 },
  commentActions: { marginTop: 8, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  deleteBtn: { margin: 0 },
  divider: { marginVertical: 4 },
  input: {},
  submit: { borderRadius: 12, marginTop: 4 },
});
