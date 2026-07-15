/**
 * Resolve a small, swappable set of style tokens from the host's emotion/MUI
 * theme (`ui_element_props.theme`), falling back to prefers-color-scheme.
 *
 * Kept pure so the presentation stays theme-aware without hard-coding a single
 * palette. The token set is intentionally tiny — this UX will be iterated on.
 */

export interface ThemeTokens {
  dark: boolean;
  bg: string;
  panel: string;
  border: string;
  text: string;
  subtext: string;
  accent: string;
  accentText: string;
  danger: string;
  disabledBg: string;
}

type JsonRecord = Record<string, unknown>;

function rec(value: unknown): JsonRecord {
  return value && typeof value === "object" ? (value as JsonRecord) : {};
}

function str(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

const LIGHT: ThemeTokens = {
  dark: false,
  bg: "#ffffff",
  panel: "#f5f6f8",
  border: "#d9dce1",
  text: "#1a1d21",
  subtext: "#6b7280",
  accent: "#2563eb",
  accentText: "#ffffff",
  danger: "#dc2626",
  disabledBg: "#e5e7eb",
};

const DARK: ThemeTokens = {
  dark: true,
  bg: "#1f2329",
  panel: "#272b31",
  border: "#3a3f47",
  text: "#e6e8eb",
  subtext: "#9aa1ab",
  accent: "#3b82f6",
  accentText: "#ffffff",
  danger: "#f87171",
  disabledBg: "#3a3f47",
};

/**
 * @param theme       host `ui_element_props.theme` (emotion theme, may be null)
 * @param prefersDark  result of prefers-color-scheme media query
 */
export function resolveTheme(
  theme: unknown,
  prefersDark: boolean,
): ThemeTokens {
  const palette = rec(rec(theme).palette);
  const mode = str(palette.mode);
  const dark = mode ? mode === "dark" : prefersDark;
  const base = dark ? DARK : LIGHT;

  const background = rec(palette.background);
  const textPalette = rec(palette.text);
  const primary = rec(palette.primary);
  const error = rec(palette.error);

  return {
    dark,
    bg: str(background.default) ?? base.bg,
    panel: str(background.paper) ?? base.panel,
    border: base.border,
    text: str(textPalette.primary) ?? base.text,
    subtext: str(textPalette.secondary) ?? base.subtext,
    accent: str(primary.main) ?? base.accent,
    accentText: str(primary.contrastText) ?? base.accentText,
    danger: str(error.main) ?? base.danger,
    disabledBg: base.disabledBg,
  };
}
