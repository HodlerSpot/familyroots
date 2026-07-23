// Root layout: mounts the global providers (React Query, Paper theme, auth)
// and an auth-gated navigator. The shared session is hydrated inside
// AuthProvider; while status is "loading" we show a centered spinner, then
// redirect between the (auth) and (app) route groups based on auth state.
import React, { useEffect } from "react";
import { ActivityIndicator, useColorScheme, View } from "react-native";
import { Slot, usePathname, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { PaperProvider, MD2Colors } from "react-native-paper";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthProvider, useAuth } from "@/auth-context";
import { AppLockProvider } from "@/app-lock";
import { queryClient } from "@/query";
import { darkTheme, lightTheme } from "@/theme";
import { setPendingInvite, takePendingInvite } from "@/pending-invite";

function AuthGate() {
  const { status } = useAuth();
  const segments = useSegments();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return;
    const inAuthGroup = segments[0] === "(auth)";
    const inAppGroup = segments[0] === "(app)";
    if (status === "unauthed" && !inAuthGroup) {
      // Preserve an invite deep link so we can complete it after sign-in.
      const match = pathname.match(/\/invites\/([^/?#]+)/);
      if (match) setPendingInvite(decodeURIComponent(match[1]));
      router.replace("/(auth)/login");
    } else if (status === "authed" && !inAppGroup) {
      // Land in the app, or straight into a pending invite if one was tapped
      // while signed out.
      const pending = takePendingInvite();
      router.replace(pending ? `/(app)/invites/${pending}` : "/(app)");
    }
  }, [status, segments, pathname, router]);

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
