/**
 * Tiny, swappable themed primitives (inline-styled from ThemeTokens). Kept
 * deliberately small — the segmenter UX is expected to be iterated on, so
 * presentation stays isolated from logic. No external UI library.
 */

import type { CSSProperties, ReactNode } from "react";
import type { ThemeTokens } from "../lib/theme.ts";

export function Card({
  tokens,
  children,
  style,
}: {
  tokens: ThemeTokens;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        background: tokens.bg,
        color: tokens.text,
        border: `1px solid ${tokens.border}`,
        borderRadius: 8,
        padding: 12,
        fontFamily:
          "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
        fontSize: 14,
        boxSizing: "border-box",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function Select({
  tokens,
  value,
  options,
  onChange,
  disabled,
  ariaLabel,
}: {
  tokens: ThemeTokens;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      style={{
        background: disabled ? tokens.disabledBg : tokens.panel,
        color: tokens.text,
        border: `1px solid ${tokens.border}`,
        borderRadius: 6,
        padding: "6px 8px",
        fontSize: 14,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.7 : 1,
        minWidth: 120,
      }}
    >
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  );
}

export function Button({
  tokens,
  children,
  onClick,
  disabled,
  variant = "primary",
  style,
}: {
  tokens: ThemeTokens;
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
  style?: CSSProperties;
}) {
  const primary = variant === "primary";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        background: primary ? tokens.accent : "transparent",
        color: primary ? tokens.accentText : tokens.accent,
        border: primary ? "none" : `1px solid ${tokens.border}`,
        borderRadius: 6,
        padding: "6px 12px",
        fontSize: 14,
        fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        ...style,
      }}
    >
      {children}
    </button>
  );
}

export function Field({
  tokens,
  label,
  children,
}: {
  tokens: ThemeTokens;
  label: string;
  children: ReactNode;
}) {
  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        fontSize: 12,
        color: tokens.subtext,
      }}
    >
      {label}
      {children}
    </label>
  );
}

export function DateTimeInput({
  tokens,
  value,
  onChange,
}: {
  tokens: ThemeTokens;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <input
      type="datetime-local"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        background: tokens.panel,
        color: tokens.text,
        border: `1px solid ${tokens.border}`,
        borderRadius: 6,
        padding: "6px 8px",
        fontSize: 14,
        colorScheme: tokens.dark ? "dark" : "light",
      }}
    />
  );
}
