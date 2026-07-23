// Your profile — the native mirror of the family half of the web account page
// (apps/web/src/app/account/page.tsx): name + email, a profile photo (the
// headshot shown when your camera is off on a call), and change password with
// the same live complexity checklist the sign-up and reset screens use.
import React, { useEffect, useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from "react-native";
import {
  ActivityIndicator,
  Button,
  Card,
  Divider,
  HelperText,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import type { UserOut } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { Avatar } from "@/components/avatar";
import { capturePhoto, pickImage } from "@/capture";
import { PasswordChecklist, passwordMeetsRules } from "@/password-rules";

export default function ProfileScreen() {
  const theme = useTheme();
  const [me, setMe] = useState<UserOut | null>(null);
  const [loadError, setLoadError] = useState("");

  // photo
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState("");
  const [photoSaved, setPhotoSaved] = useState(false);

  // password
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNext, setShowNext] = useState(false);
  const [pwBusy, setPwBusy] = useState(false);
  const [pwError, setPwError] = useState("");
  const [pwSaved, setPwSaved] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .me()
      .then((u) => active && setMe(u))
      .catch(
        (err) =>
          active &&
          setLoadError(err instanceof ApiError ? err.message : "Couldn't load your profile")
      );
    return () => {
      active = false;
    };
  }, []);

  async function updatePhoto(pick: "camera" | "library") {
    setPhotoError("");
    setPhotoSaved(false);
    try {
      const file = pick === "camera" ? await capturePhoto() : await pickImage();
      if (!file) return;
      setPhotoBusy(true);
      const updated = await api.uploadMyAvatar(file);
      setMe(updated);
      setPhotoSaved(true);
    } catch (err) {
      setPhotoError(
        err instanceof ApiError ? err.message : "We couldn't save that photo. Please try again."
      );
    } finally {
      setPhotoBusy(false);
    }
  }

  async function changePassword() {
    if (!passwordMeetsRules(next) || !current) return;
    setPwBusy(true);
    setPwError("");
    setPwSaved(false);
    try {
      await api.changePassword(current, next);
      setPwSaved(true);
      setCurrent("");
      setNext("");
    } catch (err) {
      setPwError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setPwBusy(false);
    }
  }

  if (loadError && !me) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]}>
        <View style={styles.center}>
          <Text style={{ color: theme.colors.error }}>{loadError}</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!me) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={90}
      >
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.identity}>
            <Avatar name={me.display_name} mediaId={me.avatar_media_id} size={72} />
            <View style={styles.identityText}>
              <Text variant="titleLarge" style={styles.name}>
                {me.display_name}
              </Text>
              <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                {me.email}
              </Text>
            </View>
          </View>

          <Card mode="outlined" style={styles.card}>
            <Card.Content style={styles.cardBody}>
              <Text variant="titleMedium" style={styles.heading}>
                Profile photo
              </Text>
              <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                Add a photo of yourself. When your camera is off on a family call, the family will
                see this instead.
              </Text>
              <View style={styles.photoButtons}>
                <Button
                  mode="contained-tonal"
                  icon="camera"
                  onPress={() => updatePhoto("camera")}
                  disabled={photoBusy}
                  style={styles.photoButton}
                >
                  Take a photo
                </Button>
                <Button
                  mode="outlined"
                  icon="image-multiple"
                  onPress={() => updatePhoto("library")}
                  disabled={photoBusy}
                  style={styles.photoButton}
                >
                  Choose one
                </Button>
              </View>
              {photoBusy ? <ActivityIndicator style={styles.photoBusy} /> : null}
              {photoSaved ? (
                <Text variant="bodyMedium" style={{ color: theme.colors.primary }}>
                  Looking great. Your photo is saved.
                </Text>
              ) : null}
              {photoError ? (
                <HelperText type="error" visible>
                  {photoError}
                </HelperText>
              ) : null}
            </Card.Content>
          </Card>

          <Card mode="outlined" style={styles.card}>
            <Card.Content style={styles.cardBody}>
              <Text variant="titleMedium" style={styles.heading}>
                Change your password
              </Text>
              <TextInput
                mode="outlined"
                label="Current password"
                value={current}
                onChangeText={setCurrent}
                secureTextEntry={!showCurrent}
                autoCapitalize="none"
                autoComplete="current-password"
                right={
                  <TextInput.Icon
                    icon={showCurrent ? "eye-off" : "eye"}
                    onPress={() => setShowCurrent((v) => !v)}
                  />
                }
              />
              <TextInput
                mode="outlined"
                label="New password"
                value={next}
                onChangeText={setNext}
                secureTextEntry={!showNext}
                autoCapitalize="none"
                autoComplete="password-new"
                textContentType="newPassword"
                right={
                  <TextInput.Icon
                    icon={showNext ? "eye-off" : "eye"}
                    onPress={() => setShowNext((v) => !v)}
                  />
                }
              />
              <PasswordChecklist password={next} />
              {pwSaved ? (
                <Text variant="bodyMedium" style={{ color: theme.colors.primary }}>
                  Password updated.
                </Text>
              ) : null}
              {pwError ? (
                <HelperText type="error" visible>
                  {pwError}
                </HelperText>
              ) : null}
              <Divider style={styles.divider} />
              <Button
                mode="contained"
                onPress={changePassword}
                loading={pwBusy}
                disabled={pwBusy || !passwordMeetsRules(next) || !current}
                style={styles.save}
                contentStyle={styles.saveContent}
              >
                Update password
              </Button>
            </Card.Content>
          </Card>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  content: { padding: 16, gap: 16 },
  identity: { flexDirection: "row", alignItems: "center", gap: 16 },
  identityText: { flex: 1, minWidth: 0 },
  name: { fontWeight: "700" },
  card: { borderRadius: 16 },
  cardBody: { gap: 10 },
  heading: { fontWeight: "700" },
  photoButtons: { flexDirection: "row", gap: 12, marginTop: 2 },
  photoButton: { borderRadius: 12, flex: 1 },
  photoBusy: { alignSelf: "flex-start" },
  divider: { marginVertical: 2 },
  save: { borderRadius: 12 },
  saveContent: { paddingVertical: 6 },
});
