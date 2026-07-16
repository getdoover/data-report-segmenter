/**
 * Composes the Gantt lane, the date-range picker, and the overview brush into
 * one section with a shared visible Timespan (lifted by the parent so it can
 * pre-fill the report range). Kept thin/presentational — the parent owns the
 * span state and the live segment history.
 */

import type { ThemeTokens } from "../lib/theme.ts";
import { kindColor, legendKinds, type Segment } from "../lib/timeline.ts";
import type { Timespan } from "../lib/types.ts";
import { GanttTimeline } from "./GanttTimeline.tsx";
import { TimelineBrush } from "./TimelineBrush.tsx";
import { DateRangePicker } from "./DateRangePicker.tsx";

export function TimelineSection({
  tokens,
  segments,
  dataExtent,
  span,
  onSpanChange,
  now,
  loading,
}: {
  tokens: ThemeTokens;
  segments: Segment[];
  dataExtent: Timespan | null;
  span: Timespan;
  onSpanChange: (span: Timespan) => void;
  now: number;
  loading: boolean;
}) {
  // The brush strip must always contain both the full data extent and the
  // current visible window (and "now"), so the selection window never falls
  // off the strip.
  const brushExtent: Timespan = {
    after: Math.min(span.after, dataExtent?.after ?? span.after),
    before: Math.max(span.before, dataExtent?.before ?? span.before, now),
  };
  const brushable = brushExtent.before > brushExtent.after;
  const kinds = legendKinds(segments);

  return (
    <div style={{ marginTop: 12 }}>
      {/* Chart + controls share one 75%-wide centred column. */}
      <div
        style={{
          width: "75%",
          margin: "0 auto",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {/* Date-range picker, centred above the chart. */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <DateRangePicker
            tokens={tokens}
            value={span}
            onChange={onSpanChange}
            now={now}
          />
        </div>

        <GanttTimeline
          tokens={tokens}
          segments={segments}
          span={span}
          now={now}
          loading={loading}
        />

        {brushable && (
          <TimelineBrush
            tokens={tokens}
            segments={segments}
            extent={brushExtent}
            value={span}
            onChange={onSpanChange}
          />
        )}

        {/* Legend — beneath the overview graph. */}
        {kinds.length > 0 && (
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "center",
              gap: 10,
              marginTop: 2,
            }}
          >
            {kinds.map((kind) => (
              <span
                key={kind}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  fontSize: 11,
                  color: tokens.subtext,
                }}
              >
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    background: kindColor(kind, tokens.dark),
                    display: "inline-block",
                  }}
                />
                {kind}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
