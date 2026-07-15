/**
 * Header row: `"{segments_label}: {current kind}"` with the switch dropdown to
 * the right and a subtle "since ..." line. Missing data renders the em-dash
 * placeholder rather than crashing.
 */

import {
  formatAbsolute,
  formatRelativeSince,
} from "../lib/format.ts";
import type { ThemeTokens } from "../lib/theme.ts";
import { Select } from "./ui.tsx";

const EM_DASH = "—";

export function SegmentHeader({
  tokens,
  label,
  currentKind,
  startTs,
  options,
  pendingKind,
  disabled,
  error,
  now,
  onSelect,
}: {
  tokens: ThemeTokens;
  label: string;
  currentKind: string | null;
  startTs: number | null;
  options: string[];
  pendingKind: string | null;
  disabled: boolean;
  error: string | null;
  now: number;
  onSelect: (kind: string) => void;
}) {
  const displayKind = pendingKind ?? currentKind ?? EM_DASH;
  const selectValue =
    pendingKind ?? currentKind ?? options[0] ?? EM_DASH;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 15 }}>
          <span style={{ color: tokens.subtext, fontWeight: 500 }}>
            {label}:
          </span>{" "}
          <span>{displayKind}</span>
        </div>
        <Select
          tokens={tokens}
          ariaLabel={`Switch ${label.toLowerCase()}`}
          value={selectValue}
          options={options}
          disabled={disabled}
          onChange={onSelect}
        />
      </div>

      <div style={{ fontSize: 12, color: tokens.subtext, minHeight: 16 }}>
        {pendingKind !== null ? (
          <span>Switching…</span>
        ) : startTs !== null ? (
          <span title={formatAbsolute(startTs)}>
            since {formatRelativeSince(startTs, now)}
          </span>
        ) : (
          <span>No open segment yet</span>
        )}
      </div>

      {error !== null && (
        <div style={{ fontSize: 12, color: tokens.danger }}>{error}</div>
      )}
    </div>
  );
}
