// FutureRoots design tokens — plain, framework-free constants.
//
// The web app is styled with Tailwind (emerald as the warm primary, stone as
// the neutral), and Tailwind stays authoritative there. These constants mirror
// the same palette so a non-Tailwind surface (React Native / Paper theme) can
// render the identical brand without re-deriving hex values. Values are the
// canonical Tailwind v3/v4 hex scales the web classes resolve to; the
// background/foreground pair matches apps/web/src/app/globals.css.

/** A 50–950 color ramp. */
export interface ColorScale {
  50: string;
  100: string;
  200: string;
  300: string;
  400: string;
  500: string;
  600: string;
  700: string;
  800: string;
  900: string;
  950: string;
}

/** Warm primary — used for primary actions, links, brand accents. */
export const emerald: ColorScale = {
  50: "#ecfdf5",
  100: "#d1fae5",
  200: "#a7f3d0",
  300: "#6ee7b7",
  400: "#34d399",
  500: "#10b981",
  600: "#059669",
  700: "#047857",
  800: "#065f46",
  900: "#064e3b",
  950: "#022c22",
};

/** Neutral — text, borders, surfaces (a warm gray, not slate). */
export const stone: ColorScale = {
  50: "#fafaf9",
  100: "#f5f5f4",
  200: "#e7e5e4",
  300: "#d6d3d1",
  400: "#a8a29e",
  500: "#78716c",
  600: "#57534e",
  700: "#44403c",
  800: "#292524",
  900: "#1c1917",
  950: "#0c0a09",
};

/** Destructive / error accent (danger buttons, error notes). */
export const red: ColorScale = {
  50: "#fef2f2",
  100: "#fee2e2",
  200: "#fecaca",
  300: "#fca5a5",
  400: "#f87171",
  500: "#ef4444",
  600: "#dc2626",
  700: "#b91c1c",
  800: "#991b1b",
  900: "#7f1d1d",
  950: "#450a0a",
};

/** Warning / attention accent. */
export const amber: ColorScale = {
  50: "#fffbeb",
  100: "#fef3c7",
  200: "#fde68a",
  300: "#fcd34d",
  400: "#fbbf24",
  500: "#f59e0b",
  600: "#d97706",
  700: "#b45309",
  800: "#92400e",
  900: "#78350f",
  950: "#451a03",
};

/** Soft celebratory accent (reactions, gifting flourishes). */
export const rose: ColorScale = {
  50: "#fff1f2",
  100: "#ffe4e6",
  200: "#fecdd3",
  300: "#fda4af",
  400: "#fb7185",
  500: "#f43f5e",
  600: "#e11d48",
  700: "#be123c",
  800: "#9f1239",
  900: "#881337",
  950: "#4c0519",
};

export const palette = { emerald, stone, red, amber, rose } as const;

/** Page background / foreground, light + dark (from globals.css). */
export const surface = {
  light: { background: "#ffffff", foreground: "#171717" },
  dark: { background: "#0a0a0a", foreground: "#ededed" },
} as const;

/** Semantic role tokens mapped onto the palette (light theme defaults). */
export const colors = {
  primary: emerald[700],
  primaryHover: emerald[800],
  primarySoft: emerald[50],
  primarySoftText: emerald[900],
  danger: red[600],
  dangerHover: red[700],
  text: stone[900],
  textMuted: stone[600],
  placeholder: stone[400],
  border: stone[300],
  surface: "#ffffff",
} as const;

/** Spacing scale in px (Tailwind's 4px base; key = Tailwind step). */
export const spacing = {
  0: 0,
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  16: 64,
} as const;

/** Corner radii in px. `lg` (8px) is the app's default control radius
 * (Tailwind `rounded-lg`, used on buttons/inputs/cards). */
export const radii = {
  none: 0,
  sm: 2,
  md: 6,
  lg: 8,
  xl: 12,
  "2xl": 16,
  "3xl": 24,
  full: 9999,
} as const;

export type Spacing = typeof spacing;
export type Radii = typeof radii;
