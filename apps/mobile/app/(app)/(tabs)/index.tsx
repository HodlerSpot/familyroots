// Home: the active family's hub. A tappable family header (opens the switcher
// when the member has more than one family), the monthly Memory Prompt, a
// preview of the latest moments with a link to the full feed, and a Legacy
// shortcut for full members (hidden for supporters, mirroring the web).
import React, { useState } from "react";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Divider,
  IconButton,
  Text,
  TouchableRipple,
  useTheme,
} from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { useActiveFamily } from "@/active-family";
import { MemoryPromptCard } from "@/components/memory-prompt";
import { MomentCard } from "@/components/moment-card";
import { FamilySwitcher } from "@/components/family-switcher";
import { FamilyCallCard } from "@/components/family-call/call-card";

export default function HomeScreen() {
  const router = useRouter();
  const theme = useTheme();
  const { families, activeFamily, isSupporter, loading } = useActiveFamily();
  const [switcherOpen, setSwitcherOpen] = useState(false);

  const familyId = activeFamily?.id;

  const feedQuery = useQuery({
    queryKey: ["feed", familyId],
    queryFn: () => api.familyFeed(familyId as string),
    enabled: !!familyId,
  });

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  if (!activeFamily) {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <View style={styles.emptyWrap}>
          <Text variant="headlineSmall" style={styles.title}>
            Welcome to FutureRoots
          </Text>
          <Text variant="bodyLarge" style={[styles.muted, { color: theme.colors.onSurfaceVariant }]}>
            You are not part of a family yet. When someone invites you, tap the link in your email
            and your family will show up right here.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  const latest = (feedQuery.data ?? []).slice(0, 3);
  const canSwitch = families.length > 1;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={feedQuery.isRefetching} onRefresh={() => feedQuery.refetch()} />
        }
      >
        {/* Family header + switcher */}
        <TouchableRipple
          onPress={canSwitch ? () => setSwitcherOpen(true) : undefined}
          disabled={!canSwitch}
          borderless
          style={styles.headerRipple}
          accessibilityRole={canSwitch ? "button" : undefined}
          accessibilityLabel={canSwitch ? `${activeFamily.name}. Switch family` : activeFamily.name}
        >
          <View style={styles.headerRow}>
            <View style={styles.headerText}>
              <Text variant="headlineMedium" style={[styles.title, { color: theme.colors.primary }]}>
                {activeFamily.name}
              </Text>
              <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                {roleLine(activeFamily.role)}
              </Text>
            </View>
            <View style={styles.headerActions}>
              <IconButton
                icon="account-group-outline"
                size={24}
                onPress={() => router.push("/members")}
                accessibilityLabel="Family members"
              />
              {canSwitch ? (
                <IconButton icon="swap-horizontal" size={24} onPress={() => setSwitcherOpen(true)} />
              ) : null}
            </View>
          </View>
        </TouchableRipple>

        <MemoryPromptCard familyId={activeFamily.id} />

        {/* Family video call (full members only; supporters never see it) */}
        {!isSupporter ? (
          <FamilyCallCard
            familyId={activeFamily.id}
            familyName={activeFamily.name}
            role={activeFamily.role}
          />
        ) : null}

        {/* Latest moments preview */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text variant="titleLarge" style={styles.sectionTitle}>
              Family moments
            </Text>
            {latest.length > 0 ? (
              <Button compact onPress={() => router.push("/feed")}>
                View all
              </Button>
            ) : null}
          </View>

          {feedQuery.isLoading ? (
            <ActivityIndicator style={styles.loading} />
          ) : latest.length === 0 ? (
            <Text style={{ color: theme.colors.onSurfaceVariant }}>
              No moments yet. Share a memory or celebrate a milestone and it will show up here for
              the whole family.
            </Text>
          ) : (
            <View style={styles.momentList}>
              {latest.map((e) => (
                <MomentCard key={e.id} event={e} />
              ))}
            </View>
          )}
        </View>

        {/* Legacy shortcut (full members only) */}
        {!isSupporter ? (
          <Card mode="outlined" style={styles.legacyCard}>
            <TouchableRipple borderless style={styles.legacyRipple} onPress={() => router.push("/legacy")}>
              <View style={styles.legacyInner}>
                <View style={styles.legacyText}>
                  <Text variant="titleMedium" style={{ color: theme.colors.primary }}>
                    🌳 Legacy archive
                  </Text>
                  <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                    Recipes, stories, and wisdom: your family's heritage in one place
                  </Text>
                </View>
                <Text style={{ color: theme.colors.onSurfaceVariant, fontSize: 20 }}>›</Text>
              </View>
            </TouchableRipple>
          </Card>
        ) : null}

        <Divider style={styles.bottomSpacer} />
      </ScrollView>

      <FamilySwitcher visible={switcherOpen} onDismiss={() => setSwitcherOpen(false)} />
    </SafeAreaView>
  );
}

/** A warm one-liner under the family name, tuned to the member's role. */
function roleLine(role: string): string {
  if (role === "supporter") return "You're cheering this family on";
  if (role === "parent" || role === "guardian") return "You help care for this family";
  return "Part of the family";
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 20 },
  emptyWrap: { flex: 1, padding: 24, gap: 12, justifyContent: "center" },
  headerRipple: { borderRadius: 12 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  headerText: { flex: 1, minWidth: 0 },
  headerActions: { flexDirection: "row", alignItems: "center" },
  title: { fontWeight: "700" },
  muted: {},
  section: { gap: 12 },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sectionTitle: { fontWeight: "700" },
  loading: { marginTop: 12 },
  momentList: { gap: 12 },
  legacyCard: { borderRadius: 16 },
  legacyRipple: { borderRadius: 16 },
  legacyInner: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 16,
    gap: 12,
  },
  legacyText: { flex: 1, gap: 2 },
  bottomSpacer: { opacity: 0 },
});
