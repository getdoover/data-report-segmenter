/**
 * Date-range picker matching the Doover 2.0 graph's `dateTimeRange` control:
 * an InputGroup-style trigger (two centred read-only date fields around an
 * en-dash) that opens an anchored popover holding a react-day-picker range
 * calendar, quick presets, and an Apply button.
 *
 * Styled from Doover's own shadcn/Tailwind CSS custom properties
 * (--primary, --border, --input, --muted, --popover, --radius-*, ...) with hard
 * slate-palette fallbacks, so it tracks the host theme exactly in light and
 * dark — the widget renders inside the Doover page, so those vars resolve.
 */

import { useEffect, useRef, useState } from "react";
import { DayPicker, type DateRange } from "react-day-picker";
import dayjs from "dayjs";

import type { ThemeTokens } from "../lib/theme.ts";
import { presetSpan, PRESETS } from "../lib/timeline.ts";
import type { Timespan } from "../lib/types.ts";

const DAY_MS = 24 * 60 * 60 * 1000;

// Doover theme custom properties (shadcn/Tailwind slate) with hard fallbacks.
const C = {
  primary: "var(--primary, #0f172a)",
  primaryFg: "var(--primary-foreground, #f8fafc)",
  foreground: "var(--foreground, #020617)",
  popover: "var(--popover, #ffffff)",
  input: "var(--input, #e2e8f0)",
  inputBg: "color-mix(in srgb, var(--input, #e2e8f0) 20%, transparent)",
  muted: "var(--muted, #f1f5f9)",
  mutedFg: "var(--muted-foreground, #64748b)",
  radiusMd: "var(--radius-md, 8px)",
  radiusLg: "var(--radius-lg, 10px)",
  ring: "color-mix(in srgb, var(--foreground, #020617) 10%, transparent)",
} as const;

function formatRangeBound(timestamp: number, spanMs: number): string {
  const fmt =
    spanMs > 365 * DAY_MS
      ? "MMM YYYY"
      : spanMs > 3 * DAY_MS
        ? "D MMM"
        : "D MMM HH:mm";
  return dayjs(timestamp).format(fmt);
}

export function DateRangePicker({
  value,
  onChange,
  now,
}: {
  tokens: ThemeTokens;
  value: Timespan;
  onChange: (span: Timespan) => void;
  now: number;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [range, setRange] = useState<DateRange | undefined>(() => ({
    from: dayjs(value.after).toDate(),
    to: dayjs(value.before).toDate(),
  }));
  useEffect(() => {
    setRange({
      from: dayjs(value.after).toDate(),
      to: dayjs(value.before).toDate(),
    });
  }, [value]);

  // Popover dismiss on outside click (matches base-ui popover behaviour).
  useEffect(() => {
    if (!open) {
      return;
    }
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const spanMs = value.before - value.after;

  const applyPreset = (key: (typeof PRESETS)[number]["key"]) => {
    onChange(presetSpan(key, now));
    setOpen(false);
  };

  // Once a full range exists, restart from the clicked day (matches Doover).
  const handleSelect = (next: DateRange | undefined, selectedDay: Date) => {
    setRange((current) =>
      current?.from && current?.to
        ? { from: selectedDay, to: undefined }
        : next,
    );
  };

  const applyCustom = () => {
    if (!range?.from) {
      return;
    }
    onChange({
      after: dayjs(range.from).startOf("day").valueOf(),
      before: dayjs(range.to ?? range.from)
        .endOf("day")
        .valueOf(),
    });
    setOpen(false);
  };

  const dayCell = {
    width: 36,
    height: 36,
    padding: 0,
    fontSize: 14,
    fontWeight: 400,
    color: C.foreground,
    background: "transparent",
    border: "none",
    borderRadius: C.radiusMd,
    cursor: "pointer",
  } as const;

  const selectedCell = { background: C.primary, color: C.primaryFg } as const;

  return (
    <div
      ref={wrapRef}
      style={{
        position: "relative",
        display: "inline-block",
        width: 320,
        maxWidth: "100%",
      }}
    >
      {/* Trigger: InputGroup-style, two centred fields around an en-dash. */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 28,
          width: "100%",
          boxSizing: "border-box",
          border: `1px solid ${C.input}`,
          borderRadius: C.radiusMd,
          background: C.inputBg,
          color: C.foreground,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        <span style={{ flex: 1, minWidth: 0, textAlign: "center" }}>
          {formatRangeBound(value.after, spanMs)}
        </span>
        <span style={{ color: C.mutedFg, fontSize: 12, padding: "0 6px" }}>
          –
        </span>
        <span style={{ flex: 1, minWidth: 0, textAlign: "center" }}>
          {formatRangeBound(value.before, spanMs)}
        </span>
      </div>

      {open && (
        <div
          role="dialog"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            zIndex: 1000,
            width: "auto",
            background: C.popover,
            color: C.foreground,
            borderRadius: C.radiusLg,
            padding: 10,
            // ring-1 ring-foreground/10 + shadow-md
            boxShadow: `0 0 0 1px ${C.ring}, 0 4px 6px -1px rgb(0 0 0/0.1), 0 2px 4px -2px rgb(0 0 0/0.1)`,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <DayPicker
            mode="range"
            selected={range}
            onSelect={handleSelect}
            defaultMonth={range?.from}
            numberOfMonths={1}
            styles={{
              root: { margin: 0, color: C.foreground },
              caption_label: {
                fontSize: 14,
                fontWeight: 500,
                color: C.foreground,
              },
              nav: { color: C.foreground },
              button_previous: { color: C.mutedFg, cursor: "pointer" },
              button_next: { color: C.mutedFg, cursor: "pointer" },
              chevron: { fill: C.mutedFg },
              month_caption: { padding: "2px 0" },
              weekday: {
                fontSize: 12.8,
                color: C.mutedFg,
                fontWeight: 400,
                padding: 4,
              },
              day: { textAlign: "center" },
              day_button: dayCell,
              today: { background: C.muted, color: C.foreground },
            }}
            modifiersStyles={{
              selected: selectedCell,
              range_start: selectedCell,
              range_end: selectedCell,
              range_middle: {
                background: C.muted,
                color: C.foreground,
                borderRadius: 0,
              },
            }}
          />

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 4,
              borderTop: `1px solid ${C.input}`,
              paddingTop: 8,
            }}
          >
            {PRESETS.map((preset) => (
              <button
                key={preset.key}
                type="button"
                onClick={() => applyPreset(preset.key)}
                style={{
                  flex: 1,
                  minWidth: 56,
                  height: 24,
                  padding: "0 8px",
                  fontSize: 12,
                  background: "transparent",
                  color: C.foreground,
                  border: "none",
                  borderRadius: C.radiusMd,
                  cursor: "pointer",
                }}
              >
                {preset.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={applyCustom}
            disabled={!range?.from}
            style={{
              width: "100%",
              height: 36,
              fontSize: 12,
              fontWeight: 500,
              background: C.primary,
              color: C.primaryFg,
              border: "none",
              borderRadius: C.radiusMd,
              cursor: range?.from ? "pointer" : "not-allowed",
              opacity: range?.from ? 1 : 0.5,
            }}
          >
            Apply
          </button>
        </div>
      )}
    </div>
  );
}
