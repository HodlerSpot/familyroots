// Alerts: the in-app notification inbox. Reuses /me/inbox and, like the web
// bell, marks everything read when the screen comes into focus so the tab badge
// clears (rows keep the read/unread look they had when the list loaded).
// Tapping an item routes to the relevant screen when we can map its link:
// a child link opens that child's vault (switching the active family first if
// needed), a moments link opens the feed.
import React, { useCallback } from "react";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { ActivityIndicator, Card, Divider, Text, TouchableRipple, useTheme } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { InboxItemOut } from "@futureroots/types";
import { relativeTime } from "@/format";
import { api } from "@/api";
import { useActiveFamily } from "@/active-family";

export default function AlertsScreen() {
  const router = useRouter();
  const theme = useTheme();
  const queryClient = useQueryClient();
  const { families, activeFamily, setActiveFamilyId } = useActiveFamily();

  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: () => api.inbox(20),
  });

  // Clear the badge on focus, mirroring the web bell's read-all-on-open.
  useFocusEffect(
    useCallback(() => {
      let active = true;
      void api
        .inboxReadAll()
        .then(() => {
          if (active) queryClient.invalidateQueries({ queryKey: ["inbox-unread-count"] });
        })
        .catch(() => {});
      return () => {
        active = false;
      };
    }, [queryClient])
  );

  function openItem(item: InboxItemOut) {
    void api.inboxMarkRead(item.id).catch(() => {});
    const url = item.url;
    if (!url) return;

    const childMatch = url.match(/\/family\/([^/]+)\/child\/([^/?#]+)/);
    if (childMatch) {
      const [, fid, cid] = childMatch;
      if (fid !== activeFamily?.id && families.some((f) => f.id === fid)) setActiveFamilyId(fid);
      router.push(`/child/${cid}`);
      return;
    }

    const famMatch = url.match(/\/family\/([^/?#]+)/);
    if (famMatch) {
      const fid = famMatch[1];
      if (families.some((f) => f.id === fid)) setActiveFamilyId(fid);
      if (url.includes("/moments") || url.includes("/feed")) router.push("/feed");
    }
  }

  const items = inbox.data?.items ?? [];

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={inbox.isRefetching} onRefresh={() => inbox.refetch()} />
        }
      >
        {inbox.isLoading ? (
          <ActivityIndicator style={styles.loading} />
        ) : items.length === 0 ? (
          <View style={styles.empty}>
            <Text variant="titleMedium" style={styles.emptyTitle}>
              You're all caught up.
            </Text>
            <Text style={{ color: theme.colors.onSurfaceVariant }}>
              New family moments will show up here.
            </Text>
          </View>
        ) : (
          <Card mode="outlined" style={styles.card}>
            {items.map((item, i) => {
              const unread = !item.read_at;
              return (
                <View key={item.id}>
                  {i > 0 ? <Divider /> : null}
                  <TouchableRipple
                    onPress={() => openItem(item)}
                    accessibilityRole="button"
                    accessibilityLabel={item.title}
                  >
                    <View
                      style={[
                        styles.item,
                        unread && { backgroundColor: theme.colors.primaryContainer + "40" },
                      ]}
                    >
                      <View style={styles.itemHeader}>
                        <Text
                          variant="bodyLarge"
                          style={[styles.itemTitle, unread && styles.itemTitleUnread]}
                        >
                          {item.title}
                        </Text>
                        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                          {relativeTime(item.created_at)}
                        </Text>
                      </View>
                      {item.body ? (
                        <Text
                          variant="bodyMedium"
                          style={[styles.itemBody, { color: theme.colors.onSurfaceVariant }]}
                        >
                          {item.body}
                        </Text>
                      ) : null}
                    </View>
                  </TouchableRipple>
                </View>
              );
            })}
          </Card>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { padding: 16 },
  loading: { marginTop: 24 },
  empty: { alignItems: "center", gap: 6, paddingVertical: 48, paddingHorizontal: 16 },
  emptyTitle: { fontWeight: "700" },
  card: { borderRadius: 16, overflow: "hidden" },
  item: { paddingHorizontal: 16, paddingVertical: 14, gap: 4 },
  itemHeader: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 8 },
  itemTitle: { flex: 1, fontWeight: "500" },
  itemTitleUnread: { fontWeight: "700" },
  itemBody: {},
});
