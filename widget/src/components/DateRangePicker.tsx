/**
 * Calendar date-range picker: a popover holding a react-day-picker range
 * calendar plus quick presets (24h / 7d / 30d) and Apply. Mirrors Doover's
 * `dateTimeRange` interaction (react-day-picker range mode, dayjs formatting,
 * `value:{after,before}` in / `onChange(Timespan)` out) but is fully
 * self-contained: the calendar is themed inline from ThemeTokens (no Doover
 * tailwind/shadcn CSS, no external stylesheet).
 */

import { useEffect, useRef, useState } from "react";
import { DayPicker, type DateRange } from "react-day-picker";
import dayjs from "dayjs";

import type { ThemeTokens } from "../lib/theme.ts";
import { presetSpan, PRESETS } from "../lib/timeline.ts";
import type { Timespan } from "../lib/types.ts";
import { Button } from "./ui.tsx";

const DAY_MS = 24 * 60 * 60 * 1000;

function formatRangeBound(timestamp: number, spanMs: number): string {
  const fmt =
    spanMs >= 365 * DAY_MS
      ? "MMM YYYY"
      : spanMs > 3 * DAY_MS
        ? "D MMM"
        : "D MMM HH:mm";
  return dayjs(timestamp).format(fmt);
}

export function DateRangePicker({
  tokens,
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
  const [range, setRange] = useState<DateRange | undefined>(() => ({
    from: dayjs(value.after).toDate(),
    to: dayjs(value.before).toDate(),
  }));
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setRange({
      from: dayjs(value.after).toDate(),
      to: dayjs(value.before).toDate(),
    });
  }, [value]);

  // Close on outside click.
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

  const cellStyle = {
    width: 34,
    height: 32,
    padding: 0,
    fontSize: 12,
    color: tokens.text,
    background: "transparent",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
  } as const;

  return (
    <div
      ref={wrapRef}
      style={{ position: "relative", display: "inline-block" }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          background: tokens.panel,
          color: tokens.text,
          border: `1px solid ${tokens.border}`,
          borderRadius: 6,
          padding: "6px 10px",
          fontSize: 13,
          cursor: "pointer",
          minWidth: 190,
          textAlign: "center",
        }}
      >
        {formatRangeBound(value.after, spanMs)} —{" "}
        {formatRangeBound(value.before, spanMs)}
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            zIndex: 10,
            top: "calc(100% + 4px)",
            left: 0,
            background: tokens.bg,
            color: tokens.text,
            border: `1px solid ${tokens.border}`,
            borderRadius: 8,
            padding: 10,
            boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
          }}
        >
          <DayPicker
            mode="range"
            selected={range}
            onSelect={handleSelect}
            defaultMonth={range?.from}
            numberOfMonths={1}
            styles={{
              root: { margin: 0, color: tokens.text },
              caption_label: {
                fontSize: 13,
                fontWeight: 600,
                color: tokens.text,
              },
              nav: { color: tokens.text },
              button_previous: { color: tokens.text, cursor: "pointer" },
              button_next: { color: tokens.text, cursor: "pointer" },
              chevron: { fill: tokens.text },
              month_caption: { padding: "2px 0" },
              weekday: {
                fontSize: 11,
                color: tokens.subtext,
                fontWeight: 500,
                padding: 4,
              },
              day: { textAlign: "center" },
              day_button: cellStyle,
              today: { color: tokens.accent, fontWeight: 700 },
            }}
            modifiersStyles={{
              selected: { background: tokens.accent, color: tokens.accentText },
              range_start: {
                background: tokens.accent,
                color: tokens.accentText,
              },
              range_end: {
                background: tokens.accent,
                color: tokens.accentText,
              },
              range_middle: {
                background: tokens.dark
                  ? "rgba(59,130,246,0.25)"
                  : "rgba(37,99,235,0.15)",
                color: tokens.text,
              },
            }}
          />

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
              borderTop: `1px solid ${tokens.border}`,
              paddingTop: 8,
              marginTop: 4,
            }}
          >
            {PRESETS.map((preset) => (
              <Button
                key={preset.key}
                tokens={tokens}
                variant="ghost"
                onClick={() => applyPreset(preset.key)}
                style={{ flex: 1, minWidth: 56 }}
              >
                {preset.label}
              </Button>
            ))}
          </div>

          <div style={{ marginTop: 8 }}>
            <Button
              tokens={tokens}
              onClick={applyCustom}
              disabled={!range?.from}
              style={{ width: "100%" }}
            >
              Apply
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
