// Root layout: mounts the global providers (React Query, Paper theme, auth)
// and an auth-gated navigator. The shared session is hydrated inside
// AuthProvider; while status is "loading" we show a centered spinner, then
// redirect between the (auth) and (app) route groups based on auth state.
import React, { useEffect } from "react";
import { ActivityIndicator, useColorScheme, View } from "react-native";
import { Slot, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { PaperProvider, MD2Colors } from "react-native-paper";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthProvider, useAuth } from "@/auth-context";
import { AppLockProvider } from "@/app-lock";
import { queryClient } from "@/query";
import { darkTheme, lightTheme } from "@/theme";

function AuthGate() {
  const { status } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return;
    const inAuthGroup = segments[0] === "(auth)";
    const inAppGroup = segments[0] === "(app)";
    if (status === "unauthed" && !inAuthGroup) {
      router.replace("/(auth)/login");
    } else if (status === "authed" && !inAppGroup) {
      router.replace("/(app)");
    }
  }, [status, segments, router]);

  if (status === "loading") {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator size="large" color={MD2Colors.green700} />
      </View>
    );
  }
  return <Slot />;
}

export default function RootLayout() {
  const scheme = useColorScheme();
  const theme = scheme === "dark" ? darkTheme : lightTheme;
  return (
    <QueryClientProvider client={queryClient}>
      <SafeAreaProvider>
        <PaperProvider
          theme={theme}
          settings={{ icon: (props) => <MaterialCommunityIcons {...props} /> }}
        >
          <StatusBar style={scheme === "dark" ? "light" : "dark"} />
          <AuthProvider>
            <AppLockProvider>
              <AuthGate />
            </AppLockProvider>
          </AuthProvider>
        </PaperProvider>
      </SafeAreaProvider>
    </QueryClientProvider>
  );
}
