// FutureRoots Premium — manage and gift, on the active family.
//
// Mirrors the web premium surfaces (apps/web/.../premium/page.tsx,
// premium/gift/page.tsx, and the family page's PlanSection). Copy is verbatim
// from docs/brand/premium-copy.md so both platforms speak with one voice.
//
// The buy paths (upgrade, gift, billing portal) are Stripe-hosted pages we open
// in a secure in-app browser (src/stripe-flow.ts). Because the mobile api-client
// sends X-Client-Platform, the backend returns URLs that bounce back through an
// https bridge to the futureroots:// scheme, which closes the browser; we then
// refetch plan/entitlement. Cancel and resume are plain API calls (no browser).
//
// Amounts appear only on the actual purchase surfaces (the plan cards and the
// gift form); status and upsell surfaces stay price-free and warm.
import React, { useMemo, useState } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import { Stack } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Checkbox,
  Dialog,
  HelperText,
  Portal,
  Text,
  TextInput,
  TouchableRipple,
  useTheme,
} from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useQuery } from "@tanstack/react-query";
import type { PremiumBillingPlan, PremiumStatus } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";
import { familyPhrase, formatLongDate } from "@/format";
import { openHostedFlow } from "@/stripe-flow";

const BENEFITS = [
  {
    lead: "Video memories.",
    text: "Save the recitals, first steps, and belly laughs, in the vault and on the feed.",
  },
  {
    lead: "Family video calls.",
    text: "See everyone's faces, from anywhere, and plan the next call together.",
  },
  { lead: "And everything we add next.", text: "Premium grows as FutureRoots grows." },
];

export default function PremiumScreen() {
  const theme = useTheme();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const familyName = activeFamily?.name ?? "";

  const statusQuery = useQuery({
    queryKey: ["premium", familyId],
    queryFn: () => api.getPremiumStatus(familyId as string),
    enabled: !!familyId,
  });

  async function refetch() {
    await statusQuery.refetch();
    // The family summary carries the plan badge; keep the switcher/home honest.
    void queryClient.invalidateQueries({ queryKey: ["families"] });
    void queryClient.invalidateQueries({ queryKey: ["family-detail", familyId] });
  }

  if (statusQuery.isLoading || !familyId) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  if (statusQuery.isError || !statusQuery.data) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]}>
        <View style={styles.center}>
          <Text style={{ color: theme.colors.onSurfaceVariant, textAlign: "center" }}>
            We couldn't open your plan just now. Please try again in a moment.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  const status = statusQuery.data;

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "FutureRoots Premium" }} />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {status.can_manage ? (
          <ManageView status={status} familyId={familyId} familyName={familyName} onChange={refetch} />
        ) : status.can_gift ? (
          <GiftView status={status} familyId={familyId} familyName={familyName} onChange={refetch} />
        ) : (
          <ReadOnlyView />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// --- Parent: manage the plan (upgrade / renew / cancel / resume / billing) ---

function ManageView({
  status,
  familyId,
  familyName,
  onChange,
}: {
  status: PremiumStatus;
  familyId: string;
  familyName: string;
  onChange: () => Promise<void>;
}) {
  const theme = useTheme();
  const sub = status.subscription;
  const [plan, setPlan] = useState<PremiumBillingPlan>("annual");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);

  async function checkout() {
    setBusy(true);
    setError("");
    try {
      const { checkout_url } = await api.createPremiumCheckout(familyId, plan);
      await openHostedFlow(checkout_url);
      await onChange();
    } catch (err) {
      if (err instanceof ApiError && err.code === "already_premium") {
        setError("Your family is already on Premium. There's nothing to buy twice.");
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function doCancel() {
    setBusy(true);
    setError("");
    setNote("");
    try {
      await api.cancelPremium(familyId);
      setConfirmCancel(false);
      await onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function doResume() {
    setBusy(true);
    setError("");
    try {
      await api.resumePremium(familyId);
      setNote("Welcome back. Premium continues without interruption.");
      await onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function openPortal() {
    setBusy(true);
    setError("");
    try {
      const { portal_url } = await api.createBillingPortal(familyId);
      await openHostedFlow(portal_url);
      await onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  // Already on a recurring plan: management, not a sales page.
  if (status.plan === "premium" && sub) {
    return (
      <>
        <Header
          title="FutureRoots Premium"
          subtitle="More room for your family's story. One membership covers everyone."
        />
        <Card mode="outlined" style={styles.card}>
          <Card.Content style={styles.cardBody}>
            <Text variant="titleMedium" style={[styles.pillOn, { color: theme.colors.primary }]}>
              Premium is on
            </Text>
            {sub.cancel_at_period_end ? (
              <Text variant="bodyMedium">
                Premium until {formatLongDate(sub.current_period_end)}. Auto-renewal is off.
              </Text>
            ) : (
              <Text variant="bodyMedium">
                {sub.plan === "annual" ? "Annual, $99 a year" : "Monthly, $9.99 a month"}. Renews{" "}
                {formatLongDate(sub.current_period_end)}.
              </Text>
            )}
            {sub.status === "past_due" ? (
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                The last payment didn't go through, so we'll retry automatically. Premium stays on
                for your family in the meantime.
              </Text>
            ) : null}
            {!sub.is_owner ? (
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                Started by {sub.owner_name}.
              </Text>
            ) : null}
          </Card.Content>
        </Card>

        <Grants status={status} />

        {note ? (
          <Text variant="bodyMedium" style={{ color: theme.colors.primary }}>
            {note}
          </Text>
        ) : null}

        {sub.status !== "canceled" ? (
          <View style={styles.actions}>
            {sub.cancel_at_period_end ? (
              <Button mode="contained-tonal" onPress={doResume} loading={busy} disabled={busy}>
                Resume Premium
              </Button>
            ) : (
              <Button mode="text" onPress={() => setConfirmCancel(true)} disabled={busy}>
                Cancel Premium
              </Button>
            )}
            {sub.is_owner ? (
              <Button mode="outlined" icon="credit-card-outline" onPress={openPortal} disabled={busy}>
                Manage billing
              </Button>
            ) : null}
          </View>
        ) : null}

        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}

        <Portal>
          <Dialog visible={confirmCancel} onDismiss={() => setConfirmCancel(false)}>
            <Dialog.Title>Cancel Premium?</Dialog.Title>
            <Dialog.Content>
              <Text variant="bodyMedium">
                Premium stays on until {formatLongDate(sub.current_period_end)}. After that your
                family is on the Free plan, and everything you've saved stays yours, including every
                video.
              </Text>
            </Dialog.Content>
            <Dialog.Actions>
              <Button onPress={() => setConfirmCancel(false)}>Keep Premium</Button>
              <Button onPress={doCancel} loading={busy} disabled={busy}>
                Cancel Premium
              </Button>
            </Dialog.Actions>
          </Dialog>
        </Portal>
      </>
    );
  }

  // Free, or gift-covered without a plan: show the upgrade path.
  const giftCovered = status.plan === "premium" && !!status.premium_until;
  return (
    <>
      <Header
        title="FutureRoots Premium"
        subtitle="More room for your family's story. One membership covers everyone."
      />

      {giftCovered ? (
        <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.secondaryContainer }]}>
          <Card.Content>
            <Text variant="bodyMedium" style={{ color: theme.colors.onSecondaryContainer }}>
              A gift is covering your family's Premium until{" "}
              {formatLongDate(status.premium_until as string)}. A plan you start keeps Premium going
              when the gift ends.
            </Text>
          </Card.Content>
        </Card>
      ) : null}

      <BenefitsCard />

      <View style={styles.plans}>
        <PlanCard
          selected={plan === "annual"}
          onSelect={() => setPlan("annual")}
          title="Annual"
          price="$99 a year"
          badge="Save $20.88 (about 2 months free)"
          note="Renews yearly. Cancel anytime."
        />
        <PlanCard
          selected={plan === "monthly"}
          onSelect={() => setPlan("monthly")}
          title="Monthly"
          price="$9.99 a month"
          note="Renews monthly. Cancel anytime."
        />
      </View>

      <AckRow
        checked={ack}
        onToggle={() => setAck((v) => !v)}
        text="Premium starts the moment your payment goes through. I agree to it starting right away, and I understand this means I give up the 14-day cancellation right that applies in some countries. Refund questions? Our support team is happy to help."
      />

      {error ? (
        <HelperText type="error" visible>
          {error}
        </HelperText>
      ) : null}

      <Button
        mode="contained"
        onPress={checkout}
        loading={busy}
        disabled={busy || !ack}
        style={styles.primary}
        contentStyle={styles.primaryContent}
      >
        Continue to secure checkout
      </Button>
      <Text variant="bodySmall" style={[styles.footnote, { color: theme.colors.onSurfaceVariant }]}>
        Your plan renews automatically until you cancel. Cancel anytime; your family keeps Premium
        until the end of the paid period.
      </Text>
    </>
  );
}

// --- Non-parent: gift a year of Premium ---

function GiftView({
  status,
  familyId,
  familyName,
  onChange,
}: {
  status: PremiumStatus;
  familyId: string;
  familyName: string;
  onChange: () => Promise<void>;
}) {
  const theme = useTheme();
  const [message, setMessage] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const theFamily = useMemo(() => (familyName ? familyPhrase(familyName) : "the family"), [familyName]);

  async function checkout() {
    setBusy(true);
    setError("");
    try {
      const { checkout_url } = await api.createGiftCheckout(familyId, message.trim() || undefined);
      await openHostedFlow(checkout_url);
      await onChange();
    } catch (err) {
      if (err instanceof ApiError && err.code === "use_subscribe") {
        setError("As a parent, you can start Premium for the family directly instead.");
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Header
        title={`Give ${theFamily} a year of Premium`}
        subtitle="Twelve months of video memories and family video calls, from you."
      />

      {status.plan === "premium" ? (
        <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.secondaryContainer }]}>
          <Card.Content>
            <Text variant="bodyMedium" style={{ color: theme.colors.onSecondaryContainer }}>
              This family already has Premium. Your gift will extend it by a full year, starting when
              their current coverage ends.
            </Text>
          </Card.Content>
        </Card>
      ) : null}

      <BenefitsCard />

      <Card mode="outlined" style={styles.card}>
        <Card.Content style={styles.cardBody}>
          <Text variant="bodyMedium">
            Your gift is fully prepaid. It never charges the parents, it doesn't renew, and there's
            nothing for them to set up. The whole family gets Premium the moment your gift goes
            through, and they'll see it came from you.
          </Text>
          <TextInput
            mode="outlined"
            label="Add a note the family will see (optional)"
            placeholder="For all the recital videos to come"
            value={message}
            onChangeText={setMessage}
            multiline
            maxLength={500}
          />
          <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
            Up to 500 characters. It appears on the family feed and in the parents' email.
          </Text>
        </Card.Content>
      </Card>

      <AckRow
        checked={ack}
        onToggle={() => setAck((v) => !v)}
        text="The gift year starts right away, the moment your payment goes through. I agree to it starting immediately, and I understand this means I give up the 14-day cancellation right that applies in some countries. Refund questions? Our support team is happy to help."
      />

      {error ? (
        <HelperText type="error" visible>
          {error}
        </HelperText>
      ) : null}

      <Button
        mode="contained"
        onPress={checkout}
        loading={busy}
        disabled={busy || !ack}
        style={styles.primary}
        contentStyle={styles.primaryContent}
      >
        Continue to payment
      </Button>
      <Text variant="bodySmall" style={[styles.footnote, { color: theme.colors.onSurfaceVariant }]}>
        A one-time gift of $99. Nothing renews, and no one is charged later.
      </Text>
    </>
  );
}

function ReadOnlyView() {
  const theme = useTheme();
  return (
    <>
      <Header
        title="FutureRoots Premium"
        subtitle="More room for your family's story. One membership covers everyone."
      />
      <BenefitsCard />
      <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
        A parent looks after the family's plan. Everything at the heart of FutureRoots stays free,
        always.
      </Text>
    </>
  );
}

// --- shared pieces ---

function Header({ title, subtitle }: { title: string; subtitle: string }) {
  const theme = useTheme();
  return (
    <View style={styles.header}>
      <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
        {title}
      </Text>
      <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
        {subtitle}
      </Text>
    </View>
  );
}

function BenefitsCard() {
  const theme = useTheme();
  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content style={styles.benefits}>
        {BENEFITS.map((b) => (
          <Text key={b.lead} variant="bodyMedium">
            <Text style={styles.benefitLead}>{b.lead}</Text> {b.text}
          </Text>
        ))}
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
          Photos, voice notes, milestones, contributions, goals, capsules, and the archive stay
          free, always.
        </Text>
      </Card.Content>
    </Card>
  );
}

function Grants({ status }: { status: PremiumStatus }) {
  const theme = useTheme();
  if (status.grants.length === 0) return null;
  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content style={styles.cardBody}>
        <Text variant="titleSmall">Gifts</Text>
        {status.grants.map((g, i) => (
          <View key={`${g.gifter_name}-${g.starts_at}-${i}`}>
            <Text variant="bodyMedium">
              A year of Premium from {g.gifter_name}, {formatLongDate(g.starts_at)} to{" "}
              {formatLongDate(g.ends_at)}.
            </Text>
            {g.message ? (
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant, fontStyle: "italic" }}>
                {g.message}
              </Text>
            ) : null}
          </View>
        ))}
      </Card.Content>
    </Card>
  );
}

function PlanCard({
  selected,
  onSelect,
  title,
  price,
  badge,
  note,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  price: string;
  badge?: string;
  note: string;
}) {
  const theme = useTheme();
  return (
    <TouchableRipple
      onPress={onSelect}
      borderless
      style={[
        styles.planCard,
        {
          borderColor: selected ? theme.colors.primary : theme.colors.outlineVariant,
          backgroundColor: selected ? theme.colors.primaryContainer : theme.colors.surface,
        },
      ]}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={`${title}, ${price}`}
    >
      <View style={styles.planInner}>
        <View style={styles.planTop}>
          <Text variant="titleMedium" style={styles.planTitle}>
            {title}
          </Text>
          {selected ? <Text variant="labelMedium" style={{ color: theme.colors.primary }}>Selected</Text> : null}
        </View>
        <Text variant="titleLarge" style={[styles.planPrice, { color: theme.colors.primary }]}>
          {price}
        </Text>
        {badge ? (
          <Text variant="bodySmall" style={[styles.planBadge, { color: theme.colors.onSurfaceVariant }]}>
            {badge}
          </Text>
        ) : null}
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
          {note}
        </Text>
      </View>
    </TouchableRipple>
  );
}

function AckRow({
  checked,
  onToggle,
  text,
}: {
  checked: boolean;
  onToggle: () => void;
  text: string;
}) {
  const theme = useTheme();
  return (
    <TouchableRipple onPress={onToggle} borderless style={styles.ack}>
      <View style={styles.ackRow}>
        <Checkbox status={checked ? "checked" : "unchecked"} onPress={onToggle} />
        <Text variant="bodySmall" style={[styles.ackText, { color: theme.colors.onSurfaceVariant }]}>
          {text}
        </Text>
      </View>
    </TouchableRipple>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  content: { padding: 16, gap: 16 },
  header: { gap: 4 },
  title: { fontWeight: "700" },
  card: { borderRadius: 16 },
  cardBody: { gap: 8 },
  pillOn: { fontWeight: "700" },
  benefits: { gap: 8 },
  benefitLead: { fontWeight: "700" },
  plans: { gap: 12 },
  planCard: { borderRadius: 16, borderWidth: 2 },
  planInner: { padding: 16, gap: 4 },
  planTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  planTitle: { fontWeight: "700" },
  planPrice: { fontWeight: "700" },
  planBadge: {},
  actions: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 12 },
  ack: { borderRadius: 12 },
  ackRow: { flexDirection: "row", alignItems: "flex-start", gap: 4, paddingRight: 8 },
  ackText: { flex: 1, marginTop: 8 },
  primary: { borderRadius: 12, alignSelf: "stretch" },
  primaryContent: { paddingVertical: 8 },
  footnote: { textAlign: "center" },
});
