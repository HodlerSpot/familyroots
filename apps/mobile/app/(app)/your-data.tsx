// Your data — GDPR self-serve, the native mirror of the web settings page's
// "Your data" card (export + account deletion). Copy mirrors the web
// deleted-vs-retained explainer.
//
// Download: api.exportMyData() -> write the JSON bundle to a cache file ->
// hand it to the OS share sheet (expo-sharing) so the member can save it to
// Files, email it to themselves, or send it anywhere. Media is referenced by
// id, not embedded (the bytes stay in the app).
//
// Delete: a guarded flow with a password step-up field -> api.deleteMyAccount ->
// clear the session (auth flip to the login stack) -> a warm farewell.
import React, { useState } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import {
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
import * as FileSystem from "expo-file-system";
import * as Sharing from "expo-sharing";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { useAuth } from "@/auth-context";

export default function YourDataScreen() {
  const theme = useTheme();
  const { signOut } = useAuth();

  const [downloading, setDownloading] = useState(false);
  const [exportError, setExportError] = useState("");

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [ack, setAck] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [farewell, setFarewell] = useState(false);

  async function downloadMyData() {
    setExportError("");
    setDownloading(true);
    try {
      const bundle = await api.exportMyData();
      const uri = `${FileSystem.cacheDirectory}futureroots-my-data.json`;
      await FileSystem.writeAsStringAsync(uri, JSON.stringify(bundle, null, 2), {
        encoding: FileSystem.EncodingType.UTF8,
      });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(uri, {
          mimeType: "application/json",
          dialogTitle: "Your FutureRoots data",
          UTI: "public.json",
        });
      } else {
        setExportError("Sharing isn't available on this device, so we couldn't hand off your file.");
      }
    } catch (err) {
      setExportError(
        err instanceof ApiError
          ? err.message
          : "We couldn't prepare your data just now. Please try again."
      );
    } finally {
      setDownloading(false);
    }
  }

  function openDelete() {
    setPassword("");
    setAck(false);
    setDeleteError("");
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!password || !ack || deleting) return;
    setDeleteError("");
    setDeleting(true);
    try {
      await api.deleteMyAccount(password);
      setDeleteOpen(false);
      setFarewell(true);
    } catch (err) {
      setDeleting(false);
      if (err instanceof ApiError && err.status === 403) {
        setDeleteError("That password doesn't match. Please try again.");
      } else if (err instanceof ApiError) {
        setDeleteError(err.message);
      } else {
        setDeleteError("We couldn't complete this just now. Please try again.");
      }
    }
  }

  if (farewell) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]}>
        <View style={styles.farewell}>
          <Text style={styles.emoji}>🌱</Text>
          <Text variant="headlineSmall" style={styles.farewellTitle}>
            Take good care
          </Text>
          <Text
            variant="bodyLarge"
            style={[styles.farewellBody, { color: theme.colors.onSurfaceVariant }]}
          >
            Your account is closed and your personal information has been removed. Thank you for the
            memories you helped a family keep. You're always welcome back.
          </Text>
          <Button mode="contained" style={styles.primary} contentStyle={styles.primaryContent} onPress={signOut}>
            Close
          </Button>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={styles.content}>
        <Card mode="outlined" style={styles.card}>
          <Card.Content style={styles.cardBody}>
            <Text variant="titleMedium" style={styles.heading}>
              Download a copy of your data
            </Text>
            <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
              Get everything you've added to FutureRoots in one file: your profile, your memories
              and messages, your contributions, and more. Photos and videos are listed by name so
              you can find and view them here in the app.
            </Text>
            <Button
              mode="contained-tonal"
              icon="download-outline"
              onPress={downloadMyData}
              loading={downloading}
              disabled={downloading}
              style={styles.action}
            >
              {downloading ? "Preparing your file" : "Download my data"}
            </Button>
            {exportError ? (
              <HelperText type="error" visible>
                {exportError}
              </HelperText>
            ) : null}
          </Card.Content>
        </Card>

        <Card mode="outlined" style={styles.card}>
          <Card.Content style={styles.cardBody}>
            <Text variant="titleMedium" style={styles.heading}>
              Delete my account
            </Text>
            <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
              This permanently closes your account and removes your personal information from
              FutureRoots. This can't be undone.
            </Text>
            <Button
              mode="outlined"
              textColor={theme.colors.error}
              icon="trash-can-outline"
              onPress={openDelete}
              style={styles.action}
            >
              Delete my account
            </Button>
          </Card.Content>
        </Card>
      </ScrollView>

      <Portal>
        <Dialog visible={deleteOpen} onDismiss={() => !deleting && setDeleteOpen(false)}>
          <Dialog.Title>Delete your account</Dialog.Title>
          <Dialog.ScrollArea>
            <ScrollView contentContainerStyle={styles.dialogScroll}>
              <Text variant="bodyMedium">
                We're sorry to see you go. Before you confirm, here's what happens.
              </Text>

              <View style={[styles.explainer, { backgroundColor: theme.colors.errorContainer }]}>
                <Text variant="labelLarge" style={{ color: theme.colors.onErrorContainer }}>
                  What we delete
                </Text>
                <Text variant="bodySmall" style={{ color: theme.colors.onErrorContainer }}>
                  Your profile and sign-in. The memories, messages, and other things you've added.
                  Your notification settings for this account.
                </Text>
              </View>

              <View style={[styles.explainer, { backgroundColor: theme.colors.surfaceVariant }]}>
                <Text variant="labelLarge">What we keep</Text>
                <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                  We're required by law to keep records of payments and contributions. We hold on to
                  those financial records, but we remove your name and personal details from them so
                  they're no longer connected to you.
                </Text>
              </View>

              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                This is permanent and can't be undone. To confirm, please re-enter your password.
              </Text>

              <TextInput
                mode="outlined"
                label="Your password"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoCapitalize="none"
                autoComplete="current-password"
                textContentType="password"
                disabled={deleting}
                style={styles.dialogInput}
              />

              <TouchableRipple onPress={() => !deleting && setAck((v) => !v)} borderless>
                <View style={styles.ackRow}>
                  <Checkbox status={ack ? "checked" : "unchecked"} disabled={deleting} />
                  <Text variant="bodySmall" style={styles.ackText}>
                    I understand this permanently deletes my account and can't be undone.
                  </Text>
                </View>
              </TouchableRipple>

              {deleteError ? (
                <HelperText type="error" visible>
                  {deleteError}
                </HelperText>
              ) : null}
            </ScrollView>
          </Dialog.ScrollArea>
          <Dialog.Actions>
            <Button onPress={() => setDeleteOpen(false)} disabled={deleting}>
              Keep my account
            </Button>
            <Button
              onPress={confirmDelete}
              loading={deleting}
              disabled={deleting || !password || !ack}
              textColor={theme.colors.error}
            >
              Permanently delete
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { padding: 16, gap: 16 },
  card: { borderRadius: 16 },
  cardBody: { gap: 10 },
  heading: { fontWeight: "700" },
  action: { borderRadius: 12, alignSelf: "flex-start", marginTop: 2 },
  dialogScroll: { gap: 12, paddingVertical: 8 },
  dialogInput: {},
  explainer: { borderRadius: 12, padding: 12, gap: 4 },
  ackRow: { flexDirection: "row", alignItems: "flex-start", gap: 4, paddingRight: 8 },
  ackText: { flex: 1, marginTop: 8 },
  farewell: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 12 },
  emoji: { fontSize: 52 },
  farewellTitle: { fontWeight: "700" },
  farewellBody: { textAlign: "center" },
  primary: { borderRadius: 12, marginTop: 12, alignSelf: "stretch" },
  primaryContent: { paddingVertical: 8 },
});
