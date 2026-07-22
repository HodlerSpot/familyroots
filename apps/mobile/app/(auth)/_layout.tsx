// The unauthenticated stack: login + a sign-up stub. Headerless; screens draw
// their own warm headings.
import React from "react";
import { Stack } from "expo-router";

export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
