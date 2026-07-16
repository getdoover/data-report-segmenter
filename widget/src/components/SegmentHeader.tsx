/**
 * Header row: `"{segments_label}: {current kind}"` with a "Change" button that
 * reveals the kind dropdown plus Confirm / Cancel, and a subtle "since ..."
 * line.
 *
 * Why a button + explicit Confirm rather than a bare always-visible dropdown:
 * a <select> only emits onChange when its value actually changes, so when the
 * current segment is "None" (hidden from the options) the first configured
 * kind is already the value shown and picking it fired nothing — making the
 * first switch impossible. A draft value committed on Confirm removes that
 * dependency (see initialSwitchDraft). It also guards against accidental
 * one-tap switches on a touchscreen panel.
 *
 * Missing data renders the implicit default ("None", per the spec: a freshly
 * deployed install has the None segment open) rather than crashing.
 */

import { useState } from "react";

import { formatAbsolute, formatDuration } from "../lib/format.ts";
import { initialSwitchDraft } from "../lib/options.ts";
import type { ThemeTokens } from "../lib/theme.ts";
import { CONTROL_BUTTON_WIDTH, NONE_KIND } from "../lib/types.ts";
import { Button, Select } from "./ui.tsx";

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
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>("");

  const switching = pendingKind !== null;
  // No seed yet -> the implicit default segment is "None" (spec: fresh deploy
  // opens the None segment). Show that instead of an em-dash placeholder.
  const effectiveKind = currentKind ?? NONE_KIND;
  const displayKind = pendingKind ?? effectiveKind;

  // Collapse the editor whenever a switch is in flight; it reopens (fresh) via
  // the Change button once the switch resolves.
  const showEditor = editing && !switching;

  const openEditor = () => {
    setDraft(initialSwitchDraft(options, currentKind));
    setEditing(true);
  };
  const cancel = () => setEditing(false);
  const confirm = () => {
    setEditing(false);
    // onSelect (switchTo) no-ops if the draft equals the current kind.
    onSelect(draft);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {/* 3-column grid so the change control sits at the widget's horizontal
          centre (col 2), independent of the segment label's width (col 1). */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto 1fr",
          alignItems: "center",
          gap: 12,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 15, justifySelf: "start" }}>
          <span style={{ color: tokens.subtext, fontWeight: 500 }}>
            {label}:
          </span>{" "}
          <span>{displayKind}</span>
        </div>

        <div style={{ justifySelf: "center" }}>
          {showEditor ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Select
                tokens={tokens}
                ariaLabel={`Choose ${label.toLowerCase()}`}
                value={draft}
                options={options}
                disabled={disabled}
                onChange={setDraft}
              />
              <Button
                tokens={tokens}
                variant="primary"
                disabled={disabled || draft === ""}
                onClick={confirm}
              >
                Confirm
              </Button>
              <Button tokens={tokens} variant="ghost" onClick={cancel}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              tokens={tokens}
              variant="primary"
              disabled={disabled || switching}
              onClick={openEditor}
              style={{ width: CONTROL_BUTTON_WIDTH }}
            >
              Change {label}
            </Button>
          )}
        </div>

        <div />
      </div>

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

      {error !== null && (
        <div style={{ fontSize: 12, color: tokens.danger }}>{error}</div>
      )}
    </div>
  );
}
