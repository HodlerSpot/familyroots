// Full family feed ("Family moments"): every milestone, memory, and
// celebration for the active family, newest first, each rendered by MomentCard
// (reactions inline, comments one tap away). Shares the ["feed", familyId]
// query cache with Home. Pull to refresh.
import React from "react";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { ActivityIndicator, Text, useTheme } from "react-native-paper";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { useActiveFamily } from "@/active-family";
import { MomentCard } from "@/components/moment-card";

export default function FeedScreen() {
  const theme = useTheme();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;

  const feed = useQuery({
    queryKey: ["feed", familyId],
    queryFn: () => api.familyFeed(familyId as string),
    enabled: !!familyId,
  });

  const events = feed.data ?? [];

  return (
    <ScrollView
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={feed.isRefetching} onRefresh={() => feed.refetch()} />}
    >
      <Text variant="bodyMedium" style={[styles.intro, { color: theme.colors.onSurfaceVariant }]}>
        Every milestone, memory, and celebration, all in one place for the whole family.
      </Text>

      {feed.isLoading ? (
        <ActivityIndicator style={styles.loading} />
      ) : events.length === 0 ? (
        <Text style={{ color: theme.colors.onSurfaceVariant }}>
          Nothing here yet. Add a child, share a memory, or celebrate a milestone and it will show
          up for the whole family.
        </Text>
      ) : (
        <View style={styles.list}>
          {events.map((e) => (
            <MomentCard key={e.id} event={e} />
          ))}
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12 },
  intro: { marginBottom: 4 },
  loading: { marginTop: 24 },
  list: { gap: 12 },
});
