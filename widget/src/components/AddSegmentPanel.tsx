/**
 * Retroactive "Add segment" panel: kind dropdown, start/end datetime pickers
 * (pre-filled from the visible timeline window), and Save / Cancel. Save fires
 * the add_segment RPC; the processor handles overlap-merge semantics. Dumb —
 * fire/state lives in useAddSegment.
 */

import { useEffect, useRef, useState } from "react";

import {
  fromDatetimeLocalValue,
  toDatetimeLocalValue,
} from "../lib/format.ts";
import type { ThemeTokens } from "../lib/theme.ts";
import { Button, DateTimeInput, Field, Select } from "./ui.tsx";
import type { ReportRangeDefault } from "./GenerateReportPanel.tsx";

export function AddSegmentPanel({
  tokens,
  options,
  segmentsLabel,
  pending,
  error,
  defaultRange,
  onSave,
  onCancel,
}: {
  tokens: ThemeTokens;
  options: string[];
  segmentsLabel: string;
  pending: boolean;
  error: string | null;
  defaultRange: ReportRangeDefault;
  onSave: (kind: string, startTs: number, endTs: number) => void;
  onCancel: () => void;
}) {
  const [kind, setKind] = useState<string>(options[0] ?? "None");
  const [startValue, setStartValue] = useState<string>(
    toDatetimeLocalValue(defaultRange.startTs),
  );
  const [endValue, setEndValue] = useState<string>(
    toDatetimeLocalValue(defaultRange.endTs),
  );

  // Follow the visible timeline window until the user edits the fields.
  const appliedRef = useRef<string>("");
  useEffect(() => {
    const key = `${defaultRange.startTs}:${defaultRange.endTs}`;
    if (key !== appliedRef.current) {
      appliedRef.current = key;
      setStartValue(toDatetimeLocalValue(defaultRange.startTs));
      setEndValue(toDatetimeLocalValue(defaultRange.endTs));
    }
  }, [defaultRange]);

  useEffect(() => {
    if (options.length > 0 && !options.includes(kind)) {
      setKind(options[0]);
    }
  }, [options, kind]);

  const startTs = fromDatetimeLocalValue(startValue);
  const endTs = fromDatetimeLocalValue(endValue);
  const rangeValid = startTs !== null && endTs !== null && startTs < endTs;

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
      <div style={{ fontSize: 12, color: tokens.subtext }}>
        Retroactively set a stretch of the timeline to a {segmentsLabel.toLowerCase()}
        . Overlaps of the same kind extend it; other kinds are trimmed or
        replaced.
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          alignItems: "flex-end",
        }}
      >
        <Field tokens={tokens} label={segmentsLabel}>
          <Select
            tokens={tokens}
            ariaLabel={`Add ${segmentsLabel.toLowerCase()}`}
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
          disabled={!rangeValid || pending}
          onClick={() => {
            if (rangeValid) {
              onSave(kind, startTs, endTs);
            }
          }}
        >
          {pending ? "Saving…" : "Save"}
        </Button>
        <Button tokens={tokens} variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>

      {!rangeValid && (
        <div style={{ fontSize: 12, color: tokens.danger }}>
          End time must be after start time.
        </div>
      )}
      {error !== null && (
        <div style={{ fontSize: 12, color: tokens.danger }}>{error}</div>
      )}
    </div>
  );
}
