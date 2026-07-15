/**
 * Composes the Gantt lane, the date-range picker, and the overview brush into
 * one section with a shared visible Timespan (lifted by the parent so it can
 * pre-fill the report range). Kept thin/presentational — the parent owns the
 * span state and the live segment history.
 */

import type { ThemeTokens } from "../lib/theme.ts";
import type { Segment } from "../lib/timeline.ts";
import type { Timespan } from "../lib/types.ts";
import { GanttTimeline } from "./GanttTimeline.tsx";
import { TimelineBrush } from "./TimelineBrush.tsx";
import { DateRangePicker } from "./DateRangePicker.tsx";
import { Button } from "./ui.tsx";

export function TimelineSection({
  tokens,
  segments,
  dataExtent,
  span,
  onSpanChange,
  now,
  loading,
  showReport,
  onToggleReport,
}: {
  tokens: ThemeTokens;
  segments: Segment[];
  dataExtent: Timespan | null;
  span: Timespan;
  onSpanChange: (span: Timespan) => void;
  now: number;
  loading: boolean;
  showReport: boolean;
  onToggleReport: () => void;
}) {
  // The brush strip must always contain both the full data extent and the
  // current visible window (and "now"), so the selection window never falls
  // off the strip.
  const brushExtent: Timespan = {
    after: Math.min(span.after, dataExtent?.after ?? span.after),
    before: Math.max(span.before, dataExtent?.before ?? span.before, now),
  };
  const brushable = brushExtent.before > brushExtent.after;

  return (
    <div
      style={{
        marginTop: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <Button tokens={tokens} variant="primary" onClick={onToggleReport}>
          {showReport ? "Hide Report" : "Generate Report"}
        </Button>
        <DateRangePicker
          tokens={tokens}
          value={span}
          onChange={onSpanChange}
          now={now}
        />
      </div>

      {/* Slim the chart to 75% width, centred (12.5% each side). */}
      <div style={{ width: "75%", margin: "0 auto" }}>
        <GanttTimeline
          tokens={tokens}
          segments={segments}
          span={span}
          now={now}
          loading={loading}
        />

        {brushable && (
          <div style={{ marginTop: 8 }}>
            <TimelineBrush
              tokens={tokens}
              segments={segments}
              extent={brushExtent}
              value={span}
              onChange={onSpanChange}
            />
          </div>
        )}
      </div>
    </div>
  );
}
