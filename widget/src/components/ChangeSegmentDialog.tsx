/**
 * "Change {label}" pop-up: a kind dropdown plus two ways to apply the switch —
 * **Now** (the switch happens at this instant) or **Select date** (the switch is
 * backdated to a chosen moment in the past). Plus Cancel.
 *
 * The backdated instant is clamped server-side to
 * [current segment start, now] — a switch can't open before the segment it
 * replaces began, nor in the future. The picker is bounded to the same window
 * so the UI can't offer something the processor would silently clamp.
 * Retroactively labelling stretches OUTSIDE the current segment is the Add
 * tool's job, not this one.
 */

import { useState } from "react";

import {
  fromDatetimeLocalValue,
  toDatetimeLocalValue,
} from "../lib/format.ts";
import { initialSwitchDraft } from "../lib/options.ts";
import type { ThemeTokens } from "../lib/theme.ts";
import { Button, DateTimeInput, Field, Select } from "./ui.tsx";

export function ChangeSegmentDialog({
  tokens,
  label,
  options,
  currentKind,
  startTs,
  now,
  disabled,
  onConfirm,
  onCancel,
}: {
  tokens: ThemeTokens;
  label: string;
  options: string[];
  currentKind: string | null;
  /** Current open segment's start (epoch ms) — lower bound for backdating. */
  startTs: number | null;
  now: number;
  disabled: boolean;
  /** `atTs` omitted => switch at "now". */
  onConfirm: (kind: string, atTs?: number) => void;
  onCancel: () => void;
}) {
  const [kind, setKind] = useState<string>(() =>
    initialSwitchDraft(options, currentKind),
  );
  const [picking, setPicking] = useState(false);
  const [atValue, setAtValue] = useState<string>(() =>
    toDatetimeLocalValue(now),
  );

  const atTs = fromDatetimeLocalValue(atValue);
  // Backdating is only meaningful inside the current segment.
  const lowerBound = startTs;
  const atValid =
    atTs !== null &&
    atTs <= now &&
    (lowerBound === null || atTs >= lowerBound);

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onCancel}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.4)",
          zIndex: 1000,
        }}
      />
      <div
        role="dialog"
        aria-label={`Change ${label}`}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          zIndex: 1001,
          minWidth: 280,
          maxWidth: "min(420px, calc(100vw - 2rem))",
          background: tokens.bg,
          color: tokens.text,
          border: `1px solid ${tokens.border}`,
          borderRadius: 8,
          padding: 14,
          boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 14 }}>Change {label}</div>

        <Field tokens={tokens} label={label}>
          <Select
            tokens={tokens}
            ariaLabel={`Choose ${label.toLowerCase()}`}
            value={kind}
            options={options}
            disabled={disabled}
            onChange={setKind}
          />
        </Field>

        {picking && (
          <Field tokens={tokens} label="Change takes effect">
            <DateTimeInput
              tokens={tokens}
              value={atValue}
              onChange={setAtValue}
              min={
                lowerBound !== null ? toDatetimeLocalValue(lowerBound) : undefined
              }
              max={toDatetimeLocalValue(now)}
            />
          </Field>
        )}

        {picking && !atValid && (
          <div style={{ fontSize: 12, color: tokens.danger }}>
            Pick a time between the current {label.toLowerCase()}&apos;s start
            and now.
          </div>
        )}

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            justifyContent: "flex-end",
          }}
        >
          {picking ? (
            <Button
              tokens={tokens}
              variant="primary"
              disabled={disabled || kind === "" || !atValid}
              onClick={() => atTs !== null && onConfirm(kind, atTs)}
            >
              Confirm
            </Button>
          ) : (
            <>
              <Button
                tokens={tokens}
                variant="primary"
                disabled={disabled || kind === ""}
                onClick={() => onConfirm(kind)}
              >
                Now
              </Button>
              <Button
                tokens={tokens}
                variant="ghost"
                disabled={disabled || kind === ""}
                onClick={() => setPicking(true)}
              >
                Select date
              </Button>
            </>
          )}
          <Button tokens={tokens} variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </>
  );
}
