/**
 * Header: `"{segments_label}: {current kind}"` with the segment age beneath, a
 * "Change" button, and a right-hand slot (the hamburger menu).
 *
 * Two layouts:
 *  - default (timeline shown): label / Change / menu share one row.
 *  - `centerChange` (timeline hidden): the label + menu stay pinned to the top
 *    and the Change button is centred in the remaining vertical space, so the
 *    short card doesn't look top-heavy and the menu has room to drop open.
 *
 * "Change" opens a pop-up (ChangeSegmentDialog) rather than switching inline:
 * the operator picks a kind and then either applies it **Now** or backdates it
 * via **Select date**. Committing an explicit choice from the dialog also side-
 * steps the bare-<select> trap — a <select> only fires onChange when its value
 * actually changes, so the first configured kind was previously unreachable
 * while "None" was the (hidden) current segment.
 *
 * Missing data renders the implicit default ("None", per the spec: a freshly
 * deployed install has the None segment open) rather than crashing.
 */

import { useState } from "react";
import type { ReactNode } from "react";

import { formatAbsolute, formatDuration } from "../lib/format.ts";
import type { ThemeTokens } from "../lib/theme.ts";
import { CONTROL_BUTTON_WIDTH, NONE_KIND } from "../lib/types.ts";
import { Button } from "./ui.tsx";
import { ChangeSegmentDialog } from "./ChangeSegmentDialog.tsx";

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
  rightSlot,
  centerChange = false,
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
  /** `atTs` omitted => switch at "now"; set => backdated switch instant. */
  onSelect: (kind: string, atTs?: number) => void;
  /** Rendered in the header's right column (the hamburger menu). */
  rightSlot?: ReactNode;
  /**
   * Pin the label + menu to the top and centre the Change button in the
   * remaining space. Used when the timeline chart is hidden.
   */
  centerChange?: boolean;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);

  const switching = pendingKind !== null;
  // No seed yet -> the implicit default segment is "None" (spec: fresh deploy
  // opens the None segment). Show that instead of an em-dash placeholder.
  const effectiveKind = currentKind ?? NONE_KIND;
  const displayKind = pendingKind ?? effectiveKind;

  const labelNode = (
    <div style={{ fontWeight: 600, fontSize: 15, justifySelf: "start" }}>
      <span style={{ color: tokens.subtext, fontWeight: 500 }}>{label}:</span>{" "}
      <span>{displayKind}</span>
    </div>
  );

  const changeButton = (
    <Button
      tokens={tokens}
      variant="primary"
      disabled={disabled || switching}
      onClick={() => setDialogOpen(true)}
      style={{ width: CONTROL_BUTTON_WIDTH }}
    >
      Change {label}
    </Button>
  );

  const statusRow = (
    <div style={{ fontSize: 12, color: tokens.subtext, minHeight: 16 }}>
      {switching ? (
        <span>Switching…</span>
      ) : startTs !== null ? (
        <span title={formatAbsolute(startTs)}>
          {formatDuration(now - startTs)}
        </span>
      ) : (
        <span>default — no changes recorded yet</span>
      )}
    </div>
  );

  const errorRow =
    error !== null ? (
      <div style={{ fontSize: 12, color: tokens.danger }}>{error}</div>
    ) : null;

  const dialog = dialogOpen ? (
    <ChangeSegmentDialog
      tokens={tokens}
      label={label}
      options={options}
      currentKind={currentKind}
      startTs={startTs}
      now={now}
      disabled={disabled}
      onConfirm={(kind, atTs) => {
        setDialogOpen(false);
        // onSelect (switchTo) no-ops if the kind equals the current one.
        onSelect(kind, atTs);
      }}
      onCancel={() => setDialogOpen(false)}
    />
  ) : null;

  // 3-column grid so the centre column sits at the widget's horizontal centre,
  // independent of the segment label's width (col 1).
  const gridStyle = {
    display: "grid",
    gridTemplateColumns: "1fr auto 1fr",
    alignItems: "center",
    gap: 12,
  } as const;

  if (centerChange) {
    return (
      <div
        style={{ display: "flex", flexDirection: "column", flex: 1, gap: 4 }}
      >
        <div style={gridStyle}>
          {labelNode}
          <div />
          <div style={{ justifySelf: "end" }}>{rightSlot}</div>
        </div>
        {statusRow}
        {errorRow}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {changeButton}
        </div>
        {dialog}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={gridStyle}>
        {labelNode}
        <div style={{ justifySelf: "center" }}>{changeButton}</div>
        <div style={{ justifySelf: "end" }}>{rightSlot}</div>
      </div>
      {statusRow}
      {errorRow}
      {dialog}
    </div>
  );
}
