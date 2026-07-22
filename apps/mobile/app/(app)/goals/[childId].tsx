// Goals & badges — the little wins the family sets and celebrates.
//
// Mirrors the web GoalsSection + badges card (apps/web/src/app/family/[id]/
// child/[childId]/page.tsx) in behavior and copy:
//  - Parents and guardians create a goal with a reward (a badge, cash, a Future
//    Fund gift, or a family privilege) and mark it "Done!" when it's reached.
//  - Everyone in the guardians' circle sees the goals and the badges earned.
//
// A full-member surface (the vault hides the entry for supporters). Money is
// entered in dollars and sent as integer cents; the reward-type model and copy
// come straight from web.
import React, { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { Stack, useLocalSearchParams } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Chip,
  HelperText,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { useQuery } from "@tanstack/react-query";
import { formatMoney, type RewardType } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";

const REWARD_LABELS: Record<RewardType, string> = {
  badge: "🏅 Badge",
  cash: "💵 Cash reward",
  fund_contribution: "🌳 Future fund gift",
  privilege: "⭐ Family privilege",
};

const REWARD_OPTIONS: { value: RewardType; label: string }[] = [
  { value: "badge", label: "🏅 Badge" },
  { value: "cash", label: "💵 Cash" },
  { value: "fund_contribution", label: "🌳 Future fund gift" },
  { value: "privilege", label: "⭐ Family privilege" },
];

export default function GoalsScreen() {
  const theme = useTheme();
  const { childId } = useLocalSearchParams<{ childId: string }>();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const role = activeFamily?.role ?? null;
  const canManage = role === "parent" || role === "guardian";

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });
  const childName = detail.data?.children.find((c) => c.id === childId)?.first_name ?? "";

  const goals = useQuery({
    queryKey: ["goals", childId],
    queryFn: () => api.listGoals(childId),
    enabled: !!childId,
  });
  const badges = useQuery({
    queryKey: ["badges", childId],
    queryFn: () => api.listBadges(childId),
    enabled: !!childId,
  });

  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  function refresh() {
    void goals.refetch();
    void badges.refetch();
    void detail.refetch();
  }

  async function complete(goalId: string) {
    setError("");
    try {
      await api.completeGoal(goalId);
      void queryClient.invalidateQueries({ queryKey: ["goals", childId] });
      void queryClient.invalidateQueries({ queryKey: ["badges", childId] });
      void queryClient.invalidateQueries({ queryKey: ["feed", familyId] });
      void goals.refetch();
      void badges.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    }
  }

  const goalList = goals.data ?? [];
  const badgeList = badges.data ?? [];

  if (detail.isLoading || goals.isLoading) {
    return (
      <>
        <Stack.Screen options={{ title: "Goals & badges" }} />
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: "Goals & badges" }} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={90}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={goals.isRefetching || badges.isRefetching} onRefresh={refresh} />}
        >
          {/* Badges */}
          <Card mode="outlined" style={styles.card}>
            <Card.Content style={styles.cardContent}>
              <Text variant="titleMedium" style={styles.heading}>
                🏅 Badges
              </Text>
              {badgeList.length === 0 ? (
                <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                  Badges appear when {childName || "they"} complete{childName ? "s" : ""} goals.
                </Text>
              ) : (
                <View style={styles.chipRow}>
                  {badgeList.map((b) => (
                    <Chip key={b.id} compact style={styles.badgeChip}>
                      {b.icon} {b.label}
                    </Chip>
                  ))}
                </View>
              )}
            </Card.Content>
          </Card>

          {/* Goals header + add toggle */}
          <View style={styles.headerRow}>
            <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
              Goals
            </Text>
            {canManage ? (
              <Button
                mode={showForm ? "text" : "contained-tonal"}
                icon={showForm ? undefined : "plus"}
                onPress={() => setShowForm((v) => !v)}
              >
                {showForm ? "Close" : "New goal"}
              </Button>
            ) : null}
          </View>

          {error ? (
            <HelperText type="error" visible>
              {error}
            </HelperText>
          ) : null}

          {showForm && canManage ? (
            <GoalForm
              childId={childId}
              onCreated={() => {
                setShowForm(false);
                void queryClient.invalidateQueries({ queryKey: ["goals", childId] });
                void goals.refetch();
              }}
            />
          ) : null}

          {goalList.length === 0 && !showForm ? (
            <Text variant="bodyLarge" style={{ color: theme.colors.onSurfaceVariant }}>
              {canManage
                ? `Set a goal for ${childName || "your child"} (reading, chores, practice) and celebrate when they get there.`
                : "No goals yet."}
            </Text>
          ) : null}

          <View style={styles.list}>
            {goalList.map((g) => {
              const done = g.status === "completed";
              return (
                <Card key={g.id} mode="outlined" style={[styles.card, done ? styles.doneCard : null]}>
                  <Card.Content style={styles.goalRow}>
                    <View style={styles.goalText}>
                      <Text variant="titleMedium" style={styles.goalTitle}>
                        {done ? "✅ " : ""}
                        {g.title}
                      </Text>
                      <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                        {REWARD_LABELS[g.reward_type]}
                        {g.reward_amount_cents ? ` · ${formatMoney(g.reward_amount_cents, g.currency)}` : ""}
                      </Text>
                    </View>
                    {canManage && g.status === "active" ? (
                      <Button mode="contained" compact onPress={() => complete(g.id)}>
                        Done!
                      </Button>
                    ) : null}
                  </Card.Content>
                </Card>
              );
            })}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

function GoalForm({ childId, onCreated }: { childId: string; onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [rewardType, setRewardType] = useState<RewardType>("badge");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const needsAmount = rewardType === "cash" || rewardType === "fund_contribution";
  const amountReady = !needsAmount || (parseFloat(amount || "0") > 0);
  const canCreate = title.trim().length > 0 && amountReady;

  async function create() {
    if (!canCreate) return;
    setBusy(true);
    setError("");
    try {
      await api.createGoal(childId, {
        title: title.trim(),
        reward_type: rewardType,
        reward_amount_cents: needsAmount ? Math.round(parseFloat(amount || "0") * 100) : undefined,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content style={styles.formContent}>
        <TextInput
          mode="outlined"
          label="Goal"
          placeholder="e.g. Read 10 books"
          value={title}
          onChangeText={setTitle}
        />
        <Text variant="bodyMedium">Reward</Text>
        <View style={styles.chipRow}>
          {REWARD_OPTIONS.map((r) => (
            <Chip key={r.value} selected={rewardType === r.value} showSelectedCheck onPress={() => setRewardType(r.value)} style={styles.rewardChip}>
              {r.label}
            </Chip>
          ))}
        </View>
        {needsAmount ? (
          <TextInput
            mode="outlined"
            label="Amount"
            keyboardType="decimal-pad"
            value={amount}
            onChangeText={setAmount}
            left={<TextInput.Affix text="$" />}
          />
        ) : null}
        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}
        <Button mode="contained" onPress={create} loading={busy} disabled={busy || !canCreate} style={styles.createBtn}>
          Create goal
        </Button>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 14 },
  card: { borderRadius: 16 },
  cardContent: { gap: 8 },
  heading: { fontWeight: "700" },
  title: { fontWeight: "700", flexShrink: 1 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  badgeChip: {},
  rewardChip: {},
  list: { gap: 12 },
  doneCard: { opacity: 0.7 },
  goalRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 },
  goalText: { flex: 1, minWidth: 0, gap: 2 },
  goalTitle: { fontWeight: "700" },
  formContent: { gap: 12 },
  createBtn: { borderRadius: 12, marginTop: 2 },
});
