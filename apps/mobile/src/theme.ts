// React Native Paper (Material 3) themes built from the shared design tokens,
// so the native app renders the same emerald/stone brand as the web app
// without re-deriving hex values. Light and dark variants are selected at
// runtime from the OS color scheme in the root layout.
import { MD3DarkTheme, MD3LightTheme, type MD3Theme } from "react-native-paper";
import { emerald, red, stone, surface } from "@futureroots/tokens";

export const lightTheme: MD3Theme = {
  ...MD3LightTheme,
  colors: {
    ...MD3LightTheme.colors,
    primary: emerald[700],
    onPrimary: "#ffffff",
    primaryContainer: emerald[100],
    onPrimaryContainer: emerald[900],
    secondary: emerald[600],
    error: red[600],
    onError: "#ffffff",
    background: surface.light.background,
    onBackground: surface.light.foreground,
    surface: surface.light.background,
    onSurface: surface.light.foreground,
    onSurfaceVariant: stone[600],
    outline: stone[300],
    outlineVariant: stone[200],
  },
};

export const darkTheme: MD3Theme = {
  ...MD3DarkTheme,
  colors: {
    ...MD3DarkTheme.colors,
    primary: emerald[400],
    onPrimary: emerald[950],
    primaryContainer: emerald[800],
    onPrimaryContainer: emerald[100],
    secondary: emerald[300],
    error: red[400],
    onError: red[950],
    background: surface.dark.background,
    onBackground: surface.dark.foreground,
    surface: surface.dark.background,
    onSurface: surface.dark.foreground,
    onSurfaceVariant: stone[400],
    outline: stone[600],
    outlineVariant: stone[700],
  },
};
