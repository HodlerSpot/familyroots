// Initial route ("/"): the AuthGate in the root layout redirects away from
// here as soon as auth status resolves, so this only ever flashes a spinner.
import React from "react";
import { ActivityIndicator, View } from "react-native";
import { MD2Colors } from "react-native-paper";

export default function Index() {
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
      <ActivityIndicator size="large" color={MD2Colors.green700} />
    </View>
  );
}
