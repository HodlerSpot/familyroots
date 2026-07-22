// The family-scoped bottom tab shell. Home / Kids / Alerts / Menu. The tab set
// is intentionally the same for full members and supporters in this read phase
// (the center Add action is a write flow that lands next); role gating that
// removes affordances lives inside each screen, mirroring the web isSupporter
// checks. The Alerts tab carries an unread badge from the inbox count.
import React from "react";
import { Tabs } from "expo-router";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useTheme } from "react-native-paper";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";

export default function AppTabsLayout() {
  const theme = useTheme();

  // The unread count drives the Alerts tab badge; poll gently while mounted.
  const { data: unread } = useQuery({
    queryKey: ["inbox-unread-count"],
    queryFn: () => api.inboxUnreadCount(),
    refetchInterval: 60_000,
  });
  const badge = unread && unread.count > 0 ? (unread.count > 9 ? "9+" : unread.count) : undefined;

  return (
    <Tabs
      screenOptions={{
        headerShown: true,
        headerStyle: { backgroundColor: theme.colors.surface },
        headerTitleStyle: { color: theme.colors.onSurface },
        headerShadowVisible: false,
        tabBarActiveTintColor: theme.colors.primary,
        tabBarInactiveTintColor: theme.colors.onSurfaceVariant,
        tabBarStyle: { height: 64, paddingBottom: 8, paddingTop: 6 },
        tabBarLabelStyle: { fontSize: 12 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          // The Home screen renders its own family header + switcher.
          headerShown: false,
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="home-heart" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="kids"
        options={{
          title: "Kids",
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="baby-face-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="alerts"
        options={{
          title: "Alerts",
          tabBarBadge: badge,
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="bell-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="menu"
        options={{
          title: "Menu",
          tabBarIcon: ({ color, size }) => (
            <MaterialCommunityIcons name="menu" color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}
