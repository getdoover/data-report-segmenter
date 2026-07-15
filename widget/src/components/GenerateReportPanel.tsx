/**
 * Compact "Generate Report" panel: kind dropdown (report option rules — always
 * includes "None"), start/end datetime-local pickers (default: last 7 days),
 * and a Generate button. Shows the active job's lifecycle
 * (Submitting -> Generating -> Complete/Failed) with a download button on
 * completion. Fire/watch logic lives in useGenerateReport; this stays dumb.
 */

import { useEffect, useRef, useState } from "react";

import {
  defaultReportRange,
  formatAbsolute,
  fromDatetimeLocalValue,
  toDatetimeLocalValue,
} from "../lib/format.ts";
import type { ThemeTokens } from "../lib/theme.ts";
import type { ActiveReport } from "../hooks/useGenerateReport.ts";
import { Button, DateTimeInput, Field, Select } from "./ui.tsx";

/** Optional pre-fill for the report range — the timeline's visible window. */
export interface ReportRangeDefault {
  startTs: number;
  endTs: number;
}

export function GenerateReportPanel({
  tokens,
  options,
  active,
  fireError,
  onGenerate,
  defaultRange,
}: {
  tokens: ThemeTokens;
  options: string[];
  active: ActiveReport | null;
  fireError: string | null;
  onGenerate: (kind: string, startTs: number, endTs: number) => void;
  /**
   * When present, pre-fills the start/end pickers so "what you see on the
   * timeline is what you export". Follows the visible window as it changes; the
   * user can still override the fields for a one-off report.
   */
  defaultRange?: ReportRangeDefault;
}) {
  const [kind, setKind] = useState<string>(options[0] ?? "None");
  const initial = defaultReportRange();
  const [startValue, setStartValue] = useState<string>(
    defaultRange
      ? toDatetimeLocalValue(defaultRange.startTs)
      : initial.startValue,
  );
  const [endValue, setEndValue] = useState<string>(
    defaultRange ? toDatetimeLocalValue(defaultRange.endTs) : initial.endValue,
  );

  // Follow the visible timeline window: when the incoming range changes, sync
  // the pickers to it (WYSIWYG). A ref of the last-applied values means the
  // user's own edits aren't clobbered on unrelated re-renders.
  const appliedRef = useRef<string>("");
  useEffect(() => {
    if (!defaultRange) {
      return;
    }
    const key = `${defaultRange.startTs}:${defaultRange.endTs}`;
    if (key !== appliedRef.current) {
      appliedRef.current = key;
      setStartValue(toDatetimeLocalValue(defaultRange.startTs));
      setEndValue(toDatetimeLocalValue(defaultRange.endTs));
    }
  }, [defaultRange]);

  // Keep the selected kind valid as options load/change.
  useEffect(() => {
    if (options.length > 0 && !options.includes(kind)) {
      setKind(options[0]);
    }
  }, [options, kind]);

  const startTs = fromDatetimeLocalValue(startValue);
  const endTs = fromDatetimeLocalValue(endValue);
  const rangeValid = startTs !== null && endTs !== null && startTs < endTs;

  const busy =
    active !== null &&
    (active.status === "Submitting" || active.status === "Generating");

  return (
    <div
      style={{
        marginTop: 10,
        padding: 12,
        background: tokens.panel,
        border: `1px solid ${tokens.border}`,
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          alignItems: "flex-end",
        }}
      >
        <Field tokens={tokens} label="Kind">
          <Select
            tokens={tokens}
            ariaLabel="Report kind"
            value={kind}
            options={options}
            onChange={setKind}
          />
        </Field>
        <Field tokens={tokens} label="Start">
          <DateTimeInput
            tokens={tokens}
            value={startValue}
            onChange={setStartValue}
          />
        </Field>
        <Field tokens={tokens} label="End">
          <DateTimeInput
            tokens={tokens}
            value={endValue}
            onChange={setEndValue}
          />
        </Field>
        <Button
          tokens={tokens}
          disabled={!rangeValid || busy}
          onClick={() => {
            if (rangeValid) {
              onGenerate(kind, startTs, endTs);
            }
          }}
        >
          {busy ? "Working…" : "Generate"}
        </Button>
      </div>

      {!rangeValid && (
        <div style={{ fontSize: 12, color: tokens.danger }}>
          End time must be after start time.
        </div>
      )}
      {fireError !== null && (
        <div style={{ fontSize: 12, color: tokens.danger }}>{fireError}</div>
      )}

      {active !== null && <ReportStatusLine tokens={tokens} active={active} />}
    </div>
  );
}

function ReportStatusLine({
  tokens,
  active,
}: {
  tokens: ThemeTokens;
  active: ActiveReport;
}) {
  const range = `${formatAbsolute(active.startTs)} → ${formatAbsolute(
    active.endTs,
  )}`;

  if (active.status === "Complete") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 13,
        }}
      >
        <span style={{ color: tokens.subtext }}>
          {active.kind} · {range} · ready
        </span>
        {active.download && (
          <a href={active.download.url} download={active.download.filename}>
            <Button tokens={tokens} variant="ghost">
              Download CSV
            </Button>
          </a>
        )}
      </div>
    );
  }

  if (active.status === "Failed") {
    return (
      <div style={{ fontSize: 13, color: tokens.danger }}>
        {active.kind} · {active.error ?? "Report generation failed"}
      </div>
    );
  }

  // Submitting / Generating
  return (
    <div style={{ fontSize: 13, color: tokens.subtext }}>
      {active.kind} · {range} ·{" "}
      {active.status === "Submitting" ? "submitting…" : "generating…"}
    </div>
  );
}
