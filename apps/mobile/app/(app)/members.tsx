// Family members — the native mirror of the web family page's "Family members"
// section (apps/web/src/app/family/[id]/page.tsx): the member list, inviting a
// new member, removing a member (parents), and leaving the family (everyone).
//
// Inviting: the API generates a single-use tokenized link and emails it to the
// person (exactly as on web). The token itself is never returned to the client,
// so in addition to that email we offer the OS share sheet to send them a warm
// heads-up with the app link. Guardians and parents can invite; only a parent
// can remove another member; anyone can leave (with a gentle two-step confirm,
// and a note when leaving would end a Premium subscription they started).
import React, { useState } from "react";
import { Share, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Dialog,
  Divider,
  HelperText,
  List,
  Menu,
  Portal,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useQuery } from "@tanstack/react-query";
import type { FamilyRole, MemberOut } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";
import { Avatar } from "@/components/avatar";
import { familyPhrase } from "@/format";

const ROLE_OPTIONS: { value: FamilyRole; label: string }[] = [
  { value: "grandparent", label: "Grandparent" },
  { value: "parent", label: "Parent" },
  { value: "guardian", label: "Guardian" },
  { value: "relative", label: "Relative" },
  { value: "aunt", label: "Aunt" },
  { value: "uncle", label: "Uncle" },
  { value: "cousin", label: "Cousin" },
  { value: "supporter", label: "Supporter (coach, mentor, friend)" },
];

function roleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export default function MembersScreen() {
  const theme = useTheme();
  const router = useRouter();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const myRole = activeFamily?.role ?? null;
  const canManage = myRole === "parent" || myRole === "guardian";
  const canRemove = myRole === "parent";

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });
  const meQuery = useQuery({ queryKey: ["me"], queryFn: () => api.me() });
  const meId = meQuery.data?.id ?? null;

  const [removeTarget, setRemoveTarget] = useState<MemberOut | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState("");

  const [leaveOpen, setLeaveOpen] = useState(false);
  const [leaveBusy, setLeaveBusy] = useState(false);
  const [leaveError, setLeaveError] = useState("");
  const [ownsPremium, setOwnsPremium] = useState(false);

  async function openLeave() {
    setLeaveError("");
    setOwnsPremium(false);
    setLeaveOpen(true);
    if (myRole === "parent" && familyId) {
      try {
        const s = await api.getPremiumStatus(familyId);
        setOwnsPremium(
          Boolean(s.subscription && s.subscription.is_owner && s.subscription.status !== "canceled")
        );
      } catch {
        // Keep the dialog calm and generic if the plan can't be checked.
      }
    }
  }

  async function doLeave() {
    if (!familyId) return;
    setLeaveBusy(true);
    setLeaveError("");
    try {
      await api.leaveFamily(familyId);
      await queryClient.invalidateQueries({ queryKey: ["families"] });
      setLeaveOpen(false);
      router.replace("/(app)/(tabs)");
    } catch (err) {
      setLeaveError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setLeaveBusy(false);
    }
  }

  async function doRemove() {
    if (!removeTarget || !familyId) return;
    setRemoveBusy(true);
    setRemoveError("");
    try {
      await api.removeFamilyMember(familyId, removeTarget.user.id);
      setRemoveTarget(null);
      await detail.refetch();
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setRemoveBusy(false);
    }
  }

  if (!familyId || detail.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]}>
        <View style={styles.center}>
          <Text style={{ color: theme.colors.onSurfaceVariant, textAlign: "center" }}>
            We couldn't open your family members just now. Please try again in a moment.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  const family = detail.data;

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <Card mode="outlined" style={styles.card}>
        <Card.Content style={styles.listBody}>
          {family.members.map((m, i) => (
            <View key={m.id}>
              {i > 0 ? <Divider /> : null}
              <List.Item
                title={m.user.display_name}
                titleStyle={styles.memberName}
                description={roleLabel(m.role)}
                left={() => (
                  <View style={styles.avatarWrap}>
                    <Avatar name={m.user.display_name} mediaId={m.user.avatar_media_id} size={40} />
                  </View>
                )}
                right={() =>
                  canRemove && m.user.id !== meId ? (
                    <Button
                      compact
                      mode="text"
                      textColor={theme.colors.onSurfaceVariant}
                      onPress={() => {
                        setRemoveError("");
                        setRemoveTarget(m);
                      }}
                    >
                      Remove
                    </Button>
                  ) : null
                }
              />
            </View>
          ))}
        </Card.Content>
      </Card>

      {canManage ? <InviteCard familyId={familyId} familyName={family.name} /> : null}

      <View style={styles.leaveWrap}>
        <Button mode="text" textColor={theme.colors.onSurfaceVariant} onPress={openLeave}>
          Leave this family
        </Button>
      </View>

      <Portal>
        <Dialog visible={removeTarget !== null} onDismiss={() => setRemoveTarget(null)}>
          <Dialog.Title>Remove {removeTarget?.user.display_name ?? "this member"}?</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium">
              {removeTarget?.user.display_name} won't see this family anymore. Nothing they've shared
              is deleted, and you can invite them back whenever you like.
            </Text>
            {removeError ? (
              <HelperText type="error" visible>
                {removeError}
              </HelperText>
            ) : null}
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setRemoveTarget(null)} disabled={removeBusy}>
              Keep them
            </Button>
            <Button onPress={doRemove} loading={removeBusy} disabled={removeBusy}>
              Remove
            </Button>
          </Dialog.Actions>
        </Dialog>

        <Dialog visible={leaveOpen} onDismiss={() => !leaveBusy && setLeaveOpen(false)}>
          <Dialog.Title>Leave this family?</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium">
              You can step away whenever you need to. Everything you've shared stays with the family,
              and a parent can invite you back any time.
            </Text>
            {ownsPremium ? (
              <Text variant="bodySmall" style={[styles.premiumNote, { color: theme.colors.onSurfaceVariant }]}>
                You started this family's Premium membership, so it won't renew after you leave.
                Premium stays on for everyone until the end of the current billing period.
              </Text>
            ) : null}
            {leaveError ? (
              <HelperText type="error" visible>
                {leaveError}
              </HelperText>
            ) : null}
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setLeaveOpen(false)} disabled={leaveBusy}>
              Stay
            </Button>
            <Button onPress={doLeave} loading={leaveBusy} disabled={leaveBusy}>
              Leave family
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
    </SafeAreaView>
  );
}

/** Invite a member: send the tokenized email invite, then offer the OS share
 * sheet to give them a warm heads-up with the app link. */
function InviteCard({ familyId, familyName }: { familyId: string; familyName: string }) {
  const theme = useTheme();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<FamilyRole>("grandparent");
  const [menuOpen, setMenuOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function send() {
    const clean = email.trim();
    if (!clean) return;
    setBusy(true);
    setError("");
    try {
      await api.createInvite(familyId, clean, role);
      setSentTo(clean);
      setEmail("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function shareHeadsUp() {
    const theFamily = familyName ? familyPhrase(familyName) : "our family";
    const to = sentTo ? ` (sent to ${sentTo})` : "";
    try {
      await Share.share({
        message:
          `I'd love for you to join ${theFamily} on FutureRoots, a private space where we share ` +
          `memories, celebrate milestones, and build a future together. Check your email${to} for ` +
          `your personal invitation link, or get the app at https://futureroots.app`,
      });
    } catch {
      // The member dismissed the share sheet; nothing to do.
    }
  }

  const roleText = ROLE_OPTIONS.find((r) => r.value === role)?.label ?? "Grandparent";

  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content style={styles.inviteBody}>
        <Text variant="titleMedium" style={styles.heading}>
          Invite a family member
        </Text>
        <TextInput
          mode="outlined"
          label="Their email"
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          inputMode="email"
        />
        <Menu
          visible={menuOpen}
          onDismiss={() => setMenuOpen(false)}
          anchor={
            <Button
              mode="outlined"
              icon="chevron-down"
              contentStyle={styles.roleButtonContent}
              onPress={() => setMenuOpen(true)}
              style={styles.roleButton}
            >
              They are a: {roleText}
            </Button>
          }
        >
          {ROLE_OPTIONS.map((opt) => (
            <Menu.Item
              key={opt.value}
              title={opt.label}
              onPress={() => {
                setRole(opt.value);
                setMenuOpen(false);
              }}
            />
          ))}
        </Menu>

        {sentTo ? (
          <Text variant="bodyMedium" style={{ color: theme.colors.primary }}>
            Invitation sent. They'll get an email with a link to join your family.
          </Text>
        ) : null}
        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}

        <Button
          mode="contained"
          onPress={send}
          loading={busy}
          disabled={busy || !email.trim()}
          style={styles.action}
          contentStyle={styles.actionContent}
        >
          Send invitation
        </Button>
        <Button mode="text" icon="share-variant" onPress={shareHeadsUp}>
          Share a heads-up
        </Button>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, padding: 16, gap: 16 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  card: { borderRadius: 16 },
  listBody: { paddingVertical: 4 },
  memberName: { fontWeight: "600" },
  avatarWrap: { justifyContent: "center", paddingLeft: 8 },
  inviteBody: { gap: 12 },
  heading: { fontWeight: "700" },
  roleButton: { borderRadius: 12, alignSelf: "flex-start" },
  roleButtonContent: { flexDirection: "row-reverse" },
  action: { borderRadius: 12 },
  actionContent: { paddingVertical: 6 },
  leaveWrap: { alignItems: "center", marginTop: "auto" },
  premiumNote: { marginTop: 10 },
});
