// Contribute — a gift to a child's Future Fund, from your phone.
//
// The 60-second grandparent path ends here: pick an amount (or type your own),
// add an optional note, and pay with Apple Pay / Google Pay (card as a
// fallback) through the Stripe PaymentSheet. The amount presets and the
// fee-breakdown copy mirror the web contribute page so both surfaces speak with
// one voice.
//
// Money discipline: the amount is integer cents, the fee comes from the API,
// and NO ledger math happens here. In production the contribution endpoint
// returns a PaymentIntent `client_secret`; once the PaymentSheet succeeds the
// Stripe webhook settles the append-only ledger. In LOCAL mode the provider
// settles synchronously and returns no client_secret, so we simply confirm and
// land on the thank-you screen.
//
// If the child's Future Fund isn't ready to receive gifts (none / onboarding /
// restricted) we show a warm, non-blocking note instead of a payment form.
import React, { useMemo, useState } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  HelperText,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import Constants from "expo-constants";
import * as Haptics from "expo-haptics";
import {
  PaymentSheetError,
  StripeProvider,
  useStripe,
} from "@stripe/stripe-react-native";
import { useQuery } from "@tanstack/react-query";
import { formatMoney, type ContributionOut, type FundAccountStatus } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";

// Same presets and default as the web contribute page ($25 preselected).
const PRESETS = [1000, 2500, 5000];
const DEFAULT_AMOUNT = 2500;
// Matches the merchantIdentifier declared for the Stripe config plugin in
// app.config.ts (powers Apple Pay). Not a secret; the plugin needs the same id.
const MERCHANT_ID = "merchant.com.futureroots.app";

const stripePublishableKey =
  (Constants.expoConfig?.extra?.stripePublishableKey as string | undefined) ?? "";
const appEnv = (Constants.expoConfig?.extra?.appEnv as string | undefined) ?? "development";

type Stage = "form" | "review" | "done";

export default function ContributeScreen() {
  // StripeProvider must wrap anything that calls useStripe. The publishable key
  // is public and travels in app.config.ts `extra`; when it is unset (local
  // dev) the flow never presents the sheet, so an empty key is harmless.
  return (
    <StripeProvider publishableKey={stripePublishableKey} merchantIdentifier={MERCHANT_ID}>
      <ContributeInner />
    </StripeProvider>
  );
}

function ContributeInner() {
  const theme = useTheme();
  const router = useRouter();
  const { childId } = useLocalSearchParams<{ childId: string }>();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const { initPaymentSheet, presentPaymentSheet } = useStripe();

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });
  const childName =
    detail.data?.children.find((c) => c.id === childId)?.first_name ?? "";
  const poss = childName ? `${childName}'s` : "their";

  // Gifts only flow when the fund is active. This lightweight status endpoint
  // works for supporters and full members alike (mirrors the web page).
  const fund = useQuery({
    queryKey: ["fund-status", childId],
    queryFn: () => api.fundStatus(childId),
    enabled: !!childId,
  });
  const fundStatus: FundAccountStatus | null = fund.data?.account_status ?? null;

  const [amount, setAmount] = useState<number>(DEFAULT_AMOUNT);
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState("");
  const [stage, setStage] = useState<Stage>("form");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Set once the API hands back a PaymentIntent to settle via the sheet.
  const [pending, setPending] = useState<ContributionOut | null>(null);
  // Captured for the thank-you screen (webhook settles the real balance).
  const [paid, setPaid] = useState<{ amount: number; fee: number } | null>(null);

  const effectiveAmount = useMemo(
    () => (custom ? Math.round(parseFloat(custom) * 100) || 0 : amount),
    [custom, amount]
  );

  function finish(finalAmount: number, fee: number) {
    setPaid({ amount: finalAmount, fee });
    setStage("done");
    setBusy(false);
    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    // Best-effort refresh of the surfaces a gift touches. In production the
    // ledger settles on the webhook, so the new balance may land a moment later.
    void queryClient.invalidateQueries({ queryKey: ["fund", childId] });
    void queryClient.invalidateQueries({ queryKey: ["fund-status", childId] });
    void queryClient.invalidateQueries({ queryKey: ["family-detail", familyId] });
    void queryClient.invalidateQueries({ queryKey: ["feed", familyId] });
  }

  // Step 1: create the contribution. LOCAL mode settles synchronously (no
  // client_secret) so we confirm and finish; otherwise move to the review card
  // that shows the fee breakdown before the native payment sheet.
  async function start() {
    if (effectiveAmount < 100) return;
    setBusy(true);
    setError("");
    try {
      const contribution = await api.createContribution(childId, {
        amount_cents: effectiveAmount,
        message: message.trim() || undefined,
      });
      if (contribution.client_secret) {
        setPending(contribution);
        setStage("review");
        setBusy(false);
      } else {
        // LOCAL mode: the provider already settled; just confirm the record.
        await api.confirmContribution(contribution.id);
        finish(effectiveAmount, contribution.fee_cents);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  // Step 2 (production): present Apple Pay / Google Pay / card. On success the
  // webhook writes the ledger; we never touch balances here.
  async function pay() {
    if (!pending?.client_secret) return;
    if (!stripePublishableKey) {
      setError("Payments aren't set up on this app yet. Please try again later.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { error: initError } = await initPaymentSheet({
        merchantDisplayName: "FutureRoots",
        paymentIntentClientSecret: pending.client_secret,
        applePay: { merchantCountryCode: "US" },
        googlePay: { merchantCountryCode: "US", testEnv: appEnv !== "production" },
        allowsDelayedPaymentMethods: false,
      });
      if (initError) {
        setError(initError.message || "We couldn't start the payment. Please try again.");
        setBusy(false);
        return;
      }
      const { error: sheetError } = await presentPaymentSheet();
      if (sheetError) {
        // Backing out of the sheet is not an error to shout about.
        if (sheetError.code !== PaymentSheetError.Canceled) {
          setError(sheetError.message || "The payment didn't go through. Please try again.");
        }
        setBusy(false);
        return;
      }
      finish(pending.amount_cents, pending.fee_cents);
    } catch {
      setError("The payment didn't go through. Please try again.");
      setBusy(false);
    }
  }

  const screenTitle = childName ? `A gift for ${childName}` : "Give a gift";

  // --- loading the fund status ---
  if (detail.isLoading || fund.isLoading) {
    return (
      <>
        <Stack.Screen options={{ title: screenTitle }} />
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      </>
    );
  }

  // --- couldn't read the fund status ---
  if (fund.isError || fundStatus === null) {
    return (
      <>
        <Stack.Screen options={{ title: screenTitle }} />
        <ScrollView contentContainerStyle={styles.content}>
          <NoticeCard
            emoji="🌳"
            title="We couldn't open this just now"
            body="Please try again in a moment."
            actionLabel="Go back"
            onAction={() => router.back()}
          />
        </ScrollView>
      </>
    );
  }

  // --- thank-you ---
  if (stage === "done" && paid) {
    return (
      <>
        <Stack.Screen options={{ title: "Thank you" }} />
        <ScrollView contentContainerStyle={styles.content}>
          <View style={styles.doneHead}>
            <Text style={styles.bigEmoji} accessibilityElementsHidden>
              💝
            </Text>
            <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
              You just added to {poss} future
            </Text>
            <Text variant="bodyLarge" style={[styles.center, { color: theme.colors.onSurfaceVariant }]}>
              Your {formatMoney(paid.amount)} gift{message.trim() ? " and your note are" : " is"} on{" "}
              {childName || "their"} timeline for the whole family to see, and it will be waiting for{" "}
              {childName || "them"} for years to come.
            </Text>
            {paid.fee > 0 ? (
              <Text variant="bodyMedium" style={[styles.center, { color: theme.colors.onSurfaceVariant }]}>
                {formatMoney(paid.amount - paid.fee)} is on its way to {poss} account.
              </Text>
            ) : null}
          </View>

          <Button
            mode="contained"
            icon="camera-plus-outline"
            onPress={() => router.replace(`/add-memory/${childId}`)}
            style={styles.primary}
            contentStyle={styles.primaryContent}
          >
            Leave a memory too
          </Button>
          <Button mode="text" onPress={() => router.back()}>
            All done
          </Button>
        </ScrollView>
      </>
    );
  }

  // --- fund not ready to receive gifts: warm, non-blocking ---
  if (fundStatus !== "active") {
    const paused = fundStatus === "restricted";
    return (
      <>
        <Stack.Screen options={{ title: screenTitle }} />
        <ScrollView contentContainerStyle={styles.content}>
          <NoticeCard
            emoji="🌳"
            title={
              paused
                ? `Gifts to ${childName || "this little one"} are paused just now`
                : `${childName ? `${childName}'s` : "Their"} Future Fund is on its way`
            }
            body={
              paused
                ? "The family is updating a detail. Please try again soon."
                : `${childName || "The"} family is getting the Future Fund ready. We'll be glad to see you back soon.`
            }
            actionLabel="Back to the vault"
            onAction={() => router.back()}
          />
        </ScrollView>
      </>
    );
  }

  // --- review the gift + fee breakdown, then the native payment sheet ---
  if (stage === "review" && pending) {
    return (
      <>
        <Stack.Screen options={{ title: screenTitle }} />
        <ScrollView contentContainerStyle={styles.content}>
          <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
            {formatMoney(pending.amount_cents)} for {childName || "their"} future
          </Text>

          {pending.fee_cents > 0 ? (
            <Card mode="contained" style={[styles.breakdown, { backgroundColor: theme.colors.primaryContainer }]}>
              <Card.Content style={styles.breakdownContent}>
                <FeeRow label="Your gift" value={formatMoney(pending.amount_cents)} />
                <FeeRow label="Card processing" value={formatMoney(pending.fee_cents)} muted />
                <FeeRow
                  label={`🌳 Goes straight to ${childName || "them"}`}
                  value={formatMoney(pending.amount_cents - pending.fee_cents)}
                  strong
                />
                <Text variant="bodySmall" style={{ color: theme.colors.onPrimaryContainer, marginTop: 6 }}>
                  This covers what the card costs to process. FutureRoots doesn't profit from gifts; the
                  rest is all {childName ? `${childName}'s` : "theirs"}.
                </Text>
              </Card.Content>
            </Card>
          ) : null}

          {error ? (
            <HelperText type="error" visible>
              {error}
            </HelperText>
          ) : null}

          <Button
            mode="contained"
            onPress={pay}
            loading={busy}
            disabled={busy}
            style={styles.primary}
            contentStyle={styles.primaryContent}
            icon="heart"
          >
            Send {formatMoney(pending.amount_cents)} with love
          </Button>
          <Button
            mode="text"
            onPress={() => {
              setPending(null);
              setError("");
              setStage("form");
            }}
            disabled={busy}
          >
            Change amount
          </Button>
        </ScrollView>
      </>
    );
  }

  // --- the amount form ---
  return (
    <>
      <Stack.Screen options={{ title: screenTitle }} />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.formHead}>
          <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
            Add to {childName || "their"} future
          </Text>
          <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
            A gift today, a head start tomorrow.
          </Text>
        </View>

        <View style={styles.presetRow}>
          {PRESETS.map((cents) => {
            const selected = !custom && amount === cents;
            return (
              <Button
                key={cents}
                mode={selected ? "contained" : "outlined"}
                onPress={() => {
                  setAmount(cents);
                  setCustom("");
                }}
                style={styles.preset}
                contentStyle={styles.presetContent}
                labelStyle={styles.presetLabel}
                accessibilityLabel={`Give ${formatMoney(cents)}`}
              >
                {formatMoney(cents)}
              </Button>
            );
          })}
        </View>

        <TextInput
          mode="outlined"
          label="Or another amount"
          placeholder="$"
          keyboardType="decimal-pad"
          value={custom}
          onChangeText={setCustom}
          left={<TextInput.Affix text="$" />}
        />
        <TextInput
          mode="outlined"
          label={`A note for ${childName || "them"} (optional)`}
          value={message}
          onChangeText={setMessage}
          multiline
          maxLength={2000}
        />

        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}

        <Button
          mode="contained"
          onPress={start}
          loading={busy}
          disabled={busy || effectiveAmount < 100}
          style={styles.primary}
          contentStyle={styles.primaryContent}
        >
          {`Continue with ${formatMoney(effectiveAmount)}`}
        </Button>
        <Text variant="bodySmall" style={[styles.footnote, { color: theme.colors.onSurfaceVariant }]}>
          Gifts are added to {childName || "the child"}'s Future Fund and go straight to the account
          their family chose.
        </Text>
      </ScrollView>
    </>
  );
}

function FeeRow({
  label,
  value,
  muted,
  strong,
}: {
  label: string;
  value: string;
  muted?: boolean;
  strong?: boolean;
}) {
  const theme = useTheme();
  return (
    <View style={styles.feeRow}>
      <Text
        variant={strong ? "titleMedium" : "bodyMedium"}
        style={{
          color: theme.colors.onPrimaryContainer,
          opacity: muted ? 0.75 : 1,
          fontWeight: strong ? "700" : "400",
          flex: 1,
        }}
      >
        {label}
      </Text>
      <Text
        variant={strong ? "titleMedium" : "bodyMedium"}
        style={{
          color: theme.colors.onPrimaryContainer,
          opacity: muted ? 0.75 : 1,
          fontWeight: strong ? "700" : "400",
        }}
      >
        {value}
      </Text>
    </View>
  );
}

function NoticeCard({
  emoji,
  title,
  body,
  actionLabel,
  onAction,
}: {
  emoji: string;
  title: string;
  body: string;
  actionLabel: string;
  onAction: () => void;
}) {
  const theme = useTheme();
  return (
    <View style={styles.notice}>
      <Text style={styles.bigEmoji} accessibilityElementsHidden>
        {emoji}
      </Text>
      <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
        {title}
      </Text>
      <Text variant="bodyLarge" style={[styles.center, { color: theme.colors.onSurfaceVariant }]}>
        {body}
      </Text>
      <Button mode="contained-tonal" onPress={onAction} style={styles.primary} contentStyle={styles.primaryContent}>
        {actionLabel}
      </Button>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { textAlign: "center", alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 16, flexGrow: 1 },
  title: { fontWeight: "700", textAlign: "center" },
  formHead: { gap: 4, alignItems: "center", marginTop: 4 },
  presetRow: { flexDirection: "row", gap: 10 },
  preset: { flex: 1, borderRadius: 14 },
  presetContent: { paddingVertical: 12 },
  presetLabel: { fontSize: 18, fontWeight: "700" },
  primary: { borderRadius: 12, marginTop: 4, alignSelf: "stretch" },
  primaryContent: { paddingVertical: 8 },
  footnote: { textAlign: "center", marginTop: 2 },
  breakdown: { borderRadius: 16 },
  breakdownContent: { gap: 6 },
  feeRow: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", gap: 12 },
  doneHead: { alignItems: "center", gap: 10, marginTop: 12 },
  notice: { alignItems: "center", gap: 12, marginTop: 24 },
  bigEmoji: { fontSize: 56 },
});
