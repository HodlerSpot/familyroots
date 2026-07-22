// A round avatar for a child or family member: their photo when we have a
// media id, otherwise a warm emerald monogram. Photos use the auth-header
// source (src/media.ts) since the media endpoint is protected.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import { Text, useTheme } from "react-native-paper";
import { mediaSource } from "@/media";

export function Avatar({
  name,
  mediaId,
  size = 48,
}: {
  name: string;
  mediaId?: string | null;
  size?: number;
}) {
  const theme = useTheme();
  const radius = size / 2;

  if (mediaId) {
    return (
      <Image
        source={mediaSource(mediaId)}
        style={{ width: size, height: size, borderRadius: radius }}
        contentFit="cover"
        transition={120}
        accessibilityLabel={name}
      />
    );
  }

  return (
    <View
      style={[
        styles.fallback,
        {
          width: size,
          height: size,
          borderRadius: radius,
          backgroundColor: theme.colors.primaryContainer,
        },
      ]}
    >
      <Text
        style={{ color: theme.colors.onPrimaryContainer, fontSize: size * 0.4, fontWeight: "700" }}
      >
        {(name || "?").charAt(0).toUpperCase()}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  fallback: { alignItems: "center", justifyContent: "center" },
});
