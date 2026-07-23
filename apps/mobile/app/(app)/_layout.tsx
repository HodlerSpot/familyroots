// The authenticated area is a Stack: the family-scoped tab shell is one screen
// in it, and every pushed detail screen (full feed, a moment thread, a child's
// vault, the write-flow stubs) is a sibling that slides in over the tabs with a
// native back button. The whole area is wrapped in the ActiveFamilyProvider so
// every screen reads the same active family + role.
import React from "react";
import { Stack } from "expo-router";
import { useTheme } from "react-native-paper";
import { ActiveFamilyProvider } from "@/active-family";

export default function AppLayout() {
  const theme = useTheme();
  return (
    <ActiveFamilyProvider>
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: theme.colors.surface },
          headerTintColor: theme.colors.primary,
          headerTitleStyle: { color: theme.colors.onSurface },
          headerShadowVisible: false,
          contentStyle: { backgroundColor: theme.colors.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="feed" options={{ title: "Family moments" }} />
        <Stack.Screen name="moment/[eventId]" options={{ title: "Moment" }} />
        <Stack.Screen name="child/[childId]" options={{ title: "Vault" }} />
        <Stack.Screen name="legacy" options={{ title: "Legacy archive" }} />
        <Stack.Screen name="contribute/[childId]" options={{ title: "Give a gift" }} />
        <Stack.Screen name="add-memory/[childId]" options={{ title: "Add a memory" }} />
        <Stack.Screen name="capsules/[childId]" options={{ title: "Time capsules" }} />
        <Stack.Screen name="predictions/[childId]" options={{ title: "Future predictions" }} />
        <Stack.Screen name="goals/[childId]" options={{ title: "Goals & badges" }} />
        <Stack.Screen name="premium" options={{ title: "FutureRoots Premium" }} />
        <Stack.Screen name="notifications" options={{ title: "Notifications" }} />
        <Stack.Screen name="your-data" options={{ title: "Your data" }} />
        <Stack.Screen name="profile" options={{ title: "Your profile" }} />
        <Stack.Screen name="members" options={{ title: "Family members" }} />
        <Stack.Screen name="invites/[token]" options={{ title: "Invitation" }} />
      </Stack>
    </ActiveFamilyProvider>
  );
}
