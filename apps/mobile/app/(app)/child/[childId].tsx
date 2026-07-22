// Child vault: a child's memories and milestones, with the read surface tuned
// to the viewer's role (mirroring the web vault page).
//
//  - Full members see the Future Fund summary, badges, goals, and the full
//    vault, plus entry points to the write/other flows that land in later
//    chunks (Add a memory, Contribute, Time capsules, Future predictions) as
//    stubs.
//  - Supporters see only what's shared with them: a gift card driven by the
//    lightweight fund-status endpoint, a predictions entry, and the shared
//    memories. No birthdate, no fund internals.
import React from "react";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Chip,
  Text,
  useTheme,
} from "react-native-paper";
import { useQuery } from "@tanstack/react-query";
import { formatMoney, type FundOut } from "@futureroots/types";
import { formatDurationShort } from "@/format";
import { isVideoContentType } from "@/media";
import { api } from "@/api";
import { useActiveFamily } from "@/active-family";
import { Avatar } from "@/components/avatar";
import { MediaView } from "@/components/media-view";

const TYPE_ICONS: Record<string, string> = {
  photo: "📷",
  video: "🎬",
  voice: "🎙️",
  message: "💬",
  document: "📄",
  achievement: "🏆",
};

export default function ChildVaultScreen() {
  const theme = useTheme();
  const router = useRouter();
  const { childId } = useLocalSearchParams<{ childId: string }>();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const role = activeFamily?.role ?? null;
  const isSupporter = role === "supporter";

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });
  const child = detail.data?.children.find((c) => c.id === childId) ?? null;
  const childName = child?.first_name ?? "";

  const vault = useQuery({
    queryKey: ["vault", childId],
    queryFn: () => api.listVault(childId),
    enabled: !!childId,
  });

  const fund = useQuery({
    queryKey: ["fund", childId],
    queryFn: () => api.childFund(childId),
    enabled: !!childId && !isSupporter,
  });
  const goals = useQuery({
    queryKey: ["goals", childId],
    queryFn: () => api.listGoals(childId),
    enabled: !!childId && !isSupporter,
  });
  const badges = useQuery({
    queryKey: ["badges", childId],
    queryFn: () => api.listBadges(childId),
    enabled: !!childId && !isSupporter,
  });
  const fundStatus = useQuery({
    queryKey: ["fund-status", childId],
    queryFn: () => api.fundStatus(childId),
    enabled: !!childId && isSupporter,
  });

  function refresh() {
    void detail.refetch();
    void vault.refetch();
    if (isSupporter) void fundStatus.refetch();
    else {
      void fund.refetch();
      void goals.refetch();
      void badges.refetch();
    }
  }

  const refreshing =
    vault.isRefetching ||
    detail.isRefetching ||
    fund.isRefetching ||
    goals.isRefetching ||
    badges.isRefetching ||
    fundStatus.isRefetching;

  if (detail.isLoading || vault.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  const items = vault.data ?? [];
  const seconds = child?.future_gifts_seconds;

  return (
    <>
      <Stack.Screen options={{ title: childName ? `${childName}'s vault` : "Vault" }} />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
      >
        {/* Header */}
        <View style={styles.header}>
          <Avatar name={childName} mediaId={child?.avatar_media_id} size={64} />
          <View style={styles.headerText}>
            <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
              {childName ? `${childName}'s vault` : "Vault"}
            </Text>
            <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
              Every memory added here stays with {childName || "them"} for life.
            </Text>
            {typeof seconds === "number" ? (
              <Text variant="bodySmall" style={[styles.gift, { color: theme.colors.secondary }]}>
                {seconds > 0
                  ? `🎁 Future Gifts: ${formatDurationShort(seconds)} preserved`
                  : `🎁 Start preserving moments for ${childName || "them"}.`}
              </Text>
            ) : null}
          </View>
        </View>

        {isSupporter ? (
          <>
            <SupporterGiftCard
              childName={childName}
              status={fundStatus.data?.account_status ?? null}
              onContribute={() => router.push(`/contribute/${childId}`)}
            />
            <EntryButton
              icon="crystal-ball"
              label="Future predictions"
              onPress={() => router.push(`/predictions/${childId}`)}
            />
          </>
        ) : (
          <>
            <FundCard
              fund={fund.data ?? null}
              childName={childName}
              onContribute={() => router.push(`/contribute/${childId}`)}
            />

            {/* Badges */}
            <Card mode="outlined" style={styles.card}>
              <Card.Content>
                <Text variant="titleMedium" style={styles.cardTitle}>
                  🏅 Badges
                </Text>
                {(badges.data ?? []).length === 0 ? (
                  <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                    Badges appear when {childName || "they"} complete
                    {childName ? "s" : ""} goals.
                  </Text>
                ) : (
                  <View style={styles.chipRow}>
                    {(badges.data ?? []).map((b) => (
                      <Chip key={b.id} compact icon={undefined} style={styles.badgeChip}>
                        {b.icon} {b.label}
                      </Chip>
                    ))}
                  </View>
                )}
              </Card.Content>
            </Card>

            {/* Goals (read-only summary) */}
            <Card mode="outlined" style={styles.card}>
              <Card.Content>
                <Text variant="titleMedium" style={styles.cardTitle}>
                  Goals
                </Text>
                {(goals.data ?? []).length === 0 ? (
                  <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                    No goals yet.
                  </Text>
                ) : (
                  <View style={styles.goalList}>
                    {(goals.data ?? []).map((g) => (
                      <View key={g.id} style={styles.goalRow}>
                        <Text variant="bodyLarge" style={styles.goalTitle}>
                          {g.status === "completed" ? "✅ " : "• "}
                          {g.title}
                        </Text>
                      </View>
                    ))}
                  </View>
                )}
              </Card.Content>
            </Card>

            {/* Entry points to the child's other family surfaces */}
            <View style={styles.entryRow}>
              <EntryButton
                icon="camera-plus-outline"
                label="Add a memory"
                onPress={() => router.push(`/add-memory/${childId}`)}
              />
              <EntryButton
                icon="trophy-outline"
                label="Goals & badges"
                onPress={() => router.push(`/goals/${childId}`)}
              />
              <EntryButton
                icon="mailbox-up-outline"
                label="Time capsules"
                onPress={() => router.push(`/capsules/${childId}`)}
              />
              <EntryButton
                icon="crystal-ball"
                label="Future predictions"
                onPress={() => router.push(`/predictions/${childId}`)}
              />
            </View>
          </>
        )}

        {/* Memories & milestones */}
        <Text variant="titleLarge" style={styles.sectionTitle}>
          Memories & milestones
        </Text>
        {items.length === 0 ? (
          <Text style={{ color: theme.colors.onSurfaceVariant }}>
            {isSupporter
              ? "No memories have been shared with you yet."
              : "The vault is empty. Add the first memory above."}
          </Text>
        ) : (
          <View style={styles.itemList}>
            {items.map((item) => (
              <Card key={item.id} mode="outlined" style={styles.card}>
                <Card.Content>
                  <View style={styles.itemHead}>
                    <Text style={styles.itemIcon}>{TYPE_ICONS[item.type] ?? "✨"}</Text>
                    <View style={styles.itemBody}>
                      <Text variant="titleMedium" style={styles.itemTitle}>
                        {item.title}
                      </Text>
                      {item.body ? (
                        <Text
                          variant="bodyMedium"
                          style={{ color: theme.colors.onSurfaceVariant }}
                        >
                          {item.body}
                        </Text>
                      ) : null}
                      {item.media_id &&
                      (item.media_content_type?.startsWith("image/") ||
                        isVideoContentType(item.media_content_type)) ? (
                        <View style={styles.itemMedia}>
                          <MediaView
                            mediaId={item.media_id}
                            contentType={item.media_content_type}
                            accessibilityLabel={item.title}
                          />
                        </View>
                      ) : null}
                      <Text
                        variant="bodySmall"
                        style={[styles.itemMeta, { color: theme.colors.onSurfaceVariant }]}
                      >
                        Added by {item.created_by_name} ·{" "}
                        {new Date(item.created_at).toLocaleDateString()}
                      </Text>
                      {!isSupporter && item.visible_to_supporters ? (
                        <Chip compact style={styles.sharedChip} textStyle={styles.sharedChipText}>
                          Shared with supporters
                        </Chip>
                      ) : null}
                    </View>
                  </View>
                </Card.Content>
              </Card>
            ))}
          </View>
        )}
      </ScrollView>
    </>
  );
}

/** The full-member Future Fund summary. Read-focused: shows balance + a warm
 * status line, and (when active) a working entry to the Contribute flow. */
function FundCard({
  fund,
  childName,
  onContribute,
}: {
  fund: FundOut | null;
  childName: string;
  onContribute: () => void;
}) {
  const theme = useTheme();
  const poss = childName ? `${childName}'s` : "their";

  let statusLine: string;
  if (!fund) statusLine = "…";
  else if (fund.account_status === "active")
    statusLine =
      fund.entries.length > 0
        ? `${fund.entries.length} gift${fund.entries.length === 1 ? "" : "s"} from the family`
        : "The first gift starts the journey";
  else if (fund.account_status === "onboarding") statusLine = "Almost ready. Setup is being finished.";
  else if (fund.account_status === "restricted") statusLine = "Gifts are paused for a quick check.";
  else statusLine = `A real account in ${poss} corner, growing year after year.`;

  return (
    <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.primaryContainer }]}>
      <Card.Content>
        <Text variant="titleMedium" style={[styles.cardTitle, { color: theme.colors.onPrimaryContainer }]}>
          🌳 Future fund
        </Text>
        {fund && fund.balance_cents > 0 ? (
          <Text variant="displaySmall" style={[styles.balance, { color: theme.colors.onPrimaryContainer }]}>
            {formatMoney(fund.balance_cents, fund.currency)}
          </Text>
        ) : null}
        <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
          {statusLine}
        </Text>
        {fund?.account_status === "active" ? (
          <Button mode="contained" style={styles.fundButton} onPress={onContribute}>
            Add to {poss} future
          </Button>
        ) : null}
      </Card.Content>
    </Card>
  );
}

/** The supporter gift card, driven by the lightweight fund-status endpoint
 * (supporters can't read the fund itself). Offers Contribute only when gifts
 * can actually land. */
function SupporterGiftCard({
  childName,
  status,
  onContribute,
}: {
  childName: string;
  status: string | null;
  onContribute: () => void;
}) {
  const theme = useTheme();
  const poss = childName ? `${childName}'s` : "their";

  return (
    <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.primaryContainer }]}>
      <Card.Content>
        <Text variant="titleMedium" style={[styles.cardTitle, { color: theme.colors.onPrimaryContainer }]}>
          🌳 Give a gift that grows
        </Text>
        {status === "active" ? (
          <>
            <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
              Add to {childName || "their"} future and be part of the journey.
            </Text>
            <Button mode="contained" style={styles.fundButton} onPress={onContribute}>
              Contribute to {poss} future
            </Button>
          </>
        ) : (
          <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
            {status === null
              ? "…"
              : status === "restricted"
                ? `Gifts to ${childName || "this little one"} are paused just now. Please try again soon.`
                : `${childName ? `${childName}'s` : "Their"} family is getting the Future Fund ready. We'll be glad to see you back soon.`}
          </Text>
        )}
      </Card.Content>
    </Card>
  );
}

function EntryButton({
  icon,
  label,
  onPress,
}: {
  icon: string;
  label: string;
  onPress: () => void;
}) {
  return (
    <Button
      mode="outlined"
      icon={icon}
      onPress={onPress}
      style={styles.entryButton}
      contentStyle={styles.entryButtonContent}
    >
      {label}
    </Button>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 16 },
  header: { flexDirection: "row", gap: 16, alignItems: "center" },
  headerText: { flex: 1, gap: 2 },
  title: { fontWeight: "700" },
  gift: { marginTop: 2 },
  card: { borderRadius: 16 },
  cardTitle: { fontWeight: "700", marginBottom: 6 },
  balance: { fontWeight: "700", marginBottom: 2 },
  fundButton: { marginTop: 14, borderRadius: 12 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4 },
  badgeChip: {},
  goalList: { gap: 6, marginTop: 2 },
  goalRow: {},
  goalTitle: {},
  entryRow: { gap: 10 },
  entryButton: { borderRadius: 12 },
  entryButtonContent: { paddingVertical: 6, justifyContent: "flex-start" },
  sectionTitle: { fontWeight: "700", marginTop: 4 },
  itemList: { gap: 12 },
  itemHead: { flexDirection: "row", gap: 12 },
  itemIcon: { fontSize: 22, lineHeight: 28 },
  itemBody: { flex: 1, minWidth: 0, gap: 2 },
  itemTitle: { fontWeight: "700" },
  itemMedia: { marginTop: 10 },
  itemMeta: { marginTop: 6 },
  sharedChip: { alignSelf: "flex-start", marginTop: 8 },
  sharedChipText: { fontSize: 12 },
});
