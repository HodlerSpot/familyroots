// Kids: the active family's children as tappable photo cards. Each opens that
// child's vault. Full members see a Future Gifts chip; supporters see the same
// roster (they reach a view-only vault). Pull to refresh.
import React from "react";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { ActivityIndicator, Card, Text, TouchableRipple, useTheme } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useQuery } from "@tanstack/react-query";
import { formatDurationShort } from "@/format";
import { api } from "@/api";
import { useActiveFamily } from "@/active-family";
import { Avatar } from "@/components/avatar";

export default function KidsScreen() {
  const router = useRouter();
  const theme = useTheme();
  const { activeFamily, loading } = useActiveFamily();
  const familyId = activeFamily?.id;

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });

  if (loading || (!!familyId && detail.isLoading)) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  const children = detail.data?.children ?? [];

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={detail.isRefetching} onRefresh={() => detail.refetch()} />
        }
      >
        {children.length === 0 ? (
          <Text style={{ color: theme.colors.onSurfaceVariant }}>
            No children added yet. A parent can add a child from the family on the web, and they will
            appear here.
          </Text>
        ) : (
          children.map((c) => (
            <Card key={c.id} mode="outlined" style={styles.card}>
              <TouchableRipple
                borderless
                style={styles.ripple}
                onPress={() => router.push(`/child/${c.id}`)}
                accessibilityRole="button"
                accessibilityLabel={`Open ${c.first_name}'s vault`}
              >
                <View style={styles.row}>
                  <Avatar name={c.first_name} mediaId={c.avatar_media_id} size={56} />
                  <View style={styles.info}>
                    <Text variant="titleMedium" style={styles.name}>
                      {c.first_name}
                    </Text>
                    {typeof c.future_gifts_seconds === "number" && c.future_gifts_seconds > 0 ? (
                      <Text variant="bodySmall" style={{ color: theme.colors.secondary }}>
                        🎁 {formatDurationShort(c.future_gifts_seconds)} preserved
                      </Text>
                    ) : null}
                    <Text variant="bodySmall" style={{ color: theme.colors.primary }}>
                      Open {c.first_name}'s vault ›
                    </Text>
                  </View>
                </View>
              </TouchableRipple>
            </Card>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 12 },
  card: { borderRadius: 16 },
  ripple: { borderRadius: 16 },
  row: { flexDirection: "row", alignItems: "center", gap: 16, padding: 16 },
  info: { flex: 1, gap: 2 },
  name: { fontWeight: "700" },
});
