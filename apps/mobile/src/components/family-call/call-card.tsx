// The Family Video Call card on Home (full members only; supporters never see
// it, mirroring the web isSupporter gating). Three states:
//
//   idle      -> "Gather the family..." + Start a family call
//   live      -> "Live now" + who's on + Join the call happening now
//   scheduled -> a "Next family call" row with Change / Clear
//
// FutureRoots Premium gates video calling: on a Free family the card still
// shows, but tapping Start (or Set the next call) opens the warm upsell rather
// than an error, exactly like the web callAllowed check. The API is always the
// real enforcement; a 402 backstop also routes to the upsell.
import React, { useState } from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { ActivityIndicator, Button, Card, HelperText, Text, useTheme } from "react-native-paper";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { ApiError, isPremiumRequired } from "@futureroots/api-client";
import type { CallJoin, CallState, FamilyRole } from "@futureroots/types";
import { api } from "@/api";
import { summarizeParticipants } from "@/call";
import { PremiumUpsellCard } from "@/components/premium-upsell";
import { InCallScreen } from "./in-call-screen";
import { WhoIsHereSheet } from "./who-is-here-sheet";
import { PlannedCallSheet } from "./planned-call-sheet";

type Phase = "idle" | "picking" | "in-call";

export function FamilyCallCard({
  familyId,
  familyName,
  role,
}: {
  familyId: string;
  familyName: string;
  role: FamilyRole | null;
}) {
  const router = useRouter();

  const detailQuery = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId),
  });
  const stateQuery = useQuery({
    queryKey: ["call-state", familyId],
    queryFn: () => api.callState(familyId),
    // Gently keep the live/scheduled state honest while Home is open.
    refetchInterval: 15_000,
  });

  const [phase, setPhase] = useState<Phase>("idle");
  const [join, setJoin] = useState<CallJoin | null>(null);
  const [busy, setBusy] = useState(false);
  const [joinError, setJoinError] = useState("");
  const [showUpsell, setShowUpsell] = useState(false);

  const children = detailQuery.data?.children ?? [];
  const capabilities = detailQuery.data?.capabilities;
  const callAllowed = capabilities ? capabilities.includes("family_video_call") : true;
  const state = stateQuery.data ?? null;
  const active = !!state?.active;

  function launch() {
    setJoinError("");
    if (!callAllowed) {
      setShowUpsell(true);
      return;
    }
    if (children.length === 0) void doJoin([]);
    else setPhase("picking");
  }

  async function doJoin(childIds: string[]) {
    setBusy(true);
    setJoinError("");
    try {
      const j = await api.joinCall(familyId);
      if (childIds.length > 0) {
        try {
          await api.setChildrenPresent(familyId, childIds);
        } catch {
          // Marking who's present is a nice-to-have; don't block the call.
        }
      }
      setJoin(j);
      setPhase("in-call");
    } catch (err) {
      if (isPremiumRequired(err)) {
        setShowUpsell(true);
        setPhase("idle");
        return;
      }
      setJoinError(
        err instanceof ApiError
          ? err.message
          : "We couldn't start the call just now. Please try again."
      );
      setPhase("idle");
    } finally {
      setBusy(false);
    }
  }

  function closeCall() {
    setPhase("idle");
    setJoin(null);
    void stateQuery.refetch();
  }

  return (
    <View style={styles.wrap}>
      {active ? (
        <LiveCard state={state!} busy={busy} onJoin={launch} />
      ) : (
        <IdleCard busy={busy} premiumLocked={!callAllowed} onStart={launch} />
      )}

      {joinError ? (
        <HelperText type="error" visible>
          {joinError}
        </HelperText>
      ) : null}

      {showUpsell ? (
        <PremiumUpsellCard
          capability="family_video_call"
          role={role}
          onDismiss={() => setShowUpsell(false)}
          onUpgrade={() => {
            setShowUpsell(false);
            router.push("/premium");
          }}
        />
      ) : null}

      <PlannedCallSection
        familyId={familyId}
        state={state}
        locked={!callAllowed}
        onLocked={() => setShowUpsell(true)}
        onChanged={() => void stateQuery.refetch()}
      />

      <WhoIsHereSheet
        visible={phase === "picking"}
        children={children}
        busy={busy}
        onConfirm={doJoin}
        onDismiss={() => setPhase("idle")}
      />

      {phase === "in-call" && join ? (
        <InCallScreen
          familyId={familyId}
          familyName={familyName}
          join={join}
          onClose={closeCall}
        />
      ) : null}
    </View>
  );
}

function IdleCard({
  busy,
  premiumLocked,
  onStart,
}: {
  busy: boolean;
  premiumLocked: boolean;
  onStart: () => void;
}) {
  const theme = useTheme();
  return (
    <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.primaryContainer }]}>
      <Card.Content style={styles.cardContent}>
        <View style={styles.titleRow}>
          <Text variant="titleLarge" style={[styles.cardTitle, { color: theme.colors.onPrimaryContainer }]}>
            Gather the family in the living room
          </Text>
          {premiumLocked ? <PremiumPill /> : null}
        </View>
        <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
          Start a family call and see everyone's faces, wherever they are.
        </Text>
        <Button
          mode="contained"
          icon="video"
          onPress={onStart}
          loading={busy}
          disabled={busy}
          style={styles.cta}
          contentStyle={styles.ctaContent}
        >
          Start a family call
        </Button>
      </Card.Content>
    </Card>
  );
}

function LiveCard({
  state,
  busy,
  onJoin,
}: {
  state: CallState;
  busy: boolean;
  onJoin: () => void;
}) {
  const theme = useTheme();
  const names = state.participants.map((p) => (p.is_you ? "You" : p.display_name));
  return (
    <Card mode="outlined" style={[styles.card, styles.liveCard, { borderColor: theme.colors.primary }]}>
      <Card.Content style={styles.cardContent}>
        <View style={styles.liveBadge}>
          <MaterialCommunityIcons name="record-circle" size={14} color={theme.colors.error} />
          <Text style={[styles.liveBadgeText, { color: theme.colors.onSurface }]}>Live now</Text>
        </View>
        <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
          {summarizeParticipants(names)}
        </Text>
        {state.children_present.length > 0 ? (
          <View style={styles.childrenRow}>
            {state.children_present.map((c) => (
              <View key={c.child_id} style={[styles.childChip, { backgroundColor: theme.colors.primaryContainer }]}>
                <Text style={{ color: theme.colors.onPrimaryContainer, fontSize: 13 }}>
                  {c.first_name} is here too
                </Text>
              </View>
            ))}
          </View>
        ) : null}
        <Button
          mode="contained"
          icon="video"
          onPress={onJoin}
          loading={busy}
          disabled={busy}
          style={styles.cta}
          contentStyle={styles.ctaContent}
        >
          Join the call happening now
        </Button>
      </Card.Content>
    </Card>
  );
}

function PlannedCallSection({
  familyId,
  state,
  locked,
  onLocked,
  onChanged,
}: {
  familyId: string;
  state: CallState | null;
  locked: boolean;
  onLocked: () => void;
  onChanged: () => void;
}) {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const planned = state?.planned_call ?? null;

  function startEditing() {
    if (locked) onLocked();
    else setOpen(true);
  }

  async function clear() {
    setBusy(true);
    try {
      await api.clearPlannedCall(familyId);
      onChanged();
    } catch {
      /* the poll will re-sync */
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={[styles.planned, { borderColor: theme.colors.outlineVariant }]}>
      {planned ? (
        <View style={styles.plannedRow}>
          <View style={styles.plannedText}>
            <Text variant="labelLarge" style={{ color: theme.colors.onSurfaceVariant }}>
              Next family call
            </Text>
            <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
              {formatWhen(planned.scheduled_for)}
            </Text>
            {planned.note ? (
              <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                {planned.note}
              </Text>
            ) : null}
          </View>
          <View style={styles.plannedActions}>
            <Button compact onPress={startEditing}>
              Change
            </Button>
            <Button compact textColor={theme.colors.onSurfaceVariant} onPress={clear} disabled={busy}>
              Clear
            </Button>
          </View>
        </View>
      ) : (
        <Button icon="calendar-plus" onPress={startEditing} style={styles.setNext}>
          Set the next call
        </Button>
      )}

      <PlannedCallSheet
        visible={open}
        familyId={familyId}
        initial={planned}
        onDismiss={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          onChanged();
        }}
        onPremiumNeeded={() => {
          setOpen(false);
          onLocked();
        }}
      />
    </View>
  );
}

function PremiumPill() {
  const theme = useTheme();
  return (
    <View style={[styles.pill, { backgroundColor: theme.colors.secondary }]}>
      <Text style={styles.pillText}>✨ Premium</Text>
    </View>
  );
}

/** "Sunday, July 26 at 6:00 PM". Mirrors the web formatWhen. */
function formatWhen(iso: string): string {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `${day} at ${time}`;
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  card: { borderRadius: 20 },
  liveCard: { borderWidth: 2 },
  cardContent: { gap: 12, paddingVertical: 8 },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  cardTitle: { fontWeight: "700", flexShrink: 1 },
  cta: { marginTop: 4, borderRadius: 14 },
  ctaContent: { paddingVertical: 8 },
  liveBadge: { flexDirection: "row", alignItems: "center", gap: 6 },
  liveBadgeText: { fontWeight: "700" },
  childrenRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  childChip: { borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 },
  planned: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 8 },
  plannedRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  plannedText: { flex: 1, minWidth: 0, gap: 2 },
  plannedActions: { flexDirection: "row", alignItems: "center" },
  setNext: { alignSelf: "flex-start" },
  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { color: "#ffffff", fontSize: 12, fontWeight: "700" },
});
