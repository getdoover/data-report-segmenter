/**
 * Single-lane, colour-coded Gantt of the segment history over a visible
 * Timespan. Each segment is a bar spanning [start, end], back-to-back with its
 * neighbours, coloured by kind (None muted), with an axis, a "now" marker, a
 * legend, and a hover tooltip (kind · start · end · duration).
 *
 * Presentation only: all layout maths (assembly, time->fraction, ticks,
 * colours) live in lib/timeline.ts. Bars are positioned by percentage so the
 * lane scales fluidly with its container — no horizontal page overflow.
 */

import { useState } from "react";
import type { ReactNode } from "react";

import { formatAbsolute, formatDuration } from "../lib/format.ts";
import type { ThemeTokens } from "../lib/theme.ts";
import {
  generateAxisTicks,
  kindColor,
  timeToFraction,
  type Segment,
} from "../lib/timeline.ts";
import type { Timespan } from "../lib/types.ts";

const LANE_HEIGHT = 40;

interface HoverState {
  seg: Segment;
  xPct: number;
}

export function GanttTimeline({
  tokens,
  segments,
  span,
  now,
  loading,
}: {
  tokens: ThemeTokens;
  segments: Segment[];
  span: Timespan;
  now: number;
  loading: boolean;
}) {
  const [hover, setHover] = useState<HoverState | null>(null);

  const ticks = generateAxisTicks(span, 6);
  const nowFrac =
    now >= span.after && now <= span.before ? timeToFraction(now, span) : null;

  // Draw rects: clip each segment to the span but keep original bounds for the
  // tooltip.
  const bars = segments
    .map((seg) => {
      const drawStart = Math.max(seg.start, span.after);
      const drawEnd = Math.min(seg.end, span.before);
      if (drawEnd <= drawStart) {
        return null;
      }
      const leftPct = timeToFraction(drawStart, span) * 100;
      const widthPct =
        (timeToFraction(drawEnd, span) - timeToFraction(drawStart, span)) * 100;
      return { seg, leftPct, widthPct };
    })
    .filter(
      (b): b is { seg: Segment; leftPct: number; widthPct: number } =>
        b !== null,
    );

  return (
    <div style={{ width: "100%", boxSizing: "border-box" }}>
      {/* Lane */}
      <div
        style={{
          position: "relative",
          height: LANE_HEIGHT,
          background: tokens.panel,
          border: `1px solid ${tokens.border}`,
          borderRadius: 6,
          overflow: "hidden",
        }}
        onMouseLeave={() => setHover(null)}
      >
        {loading ? (
          <Centered tokens={tokens}>Loading timeline…</Centered>
        ) : bars.length === 0 ? (
          <Centered tokens={tokens}>No segments in this range</Centered>
        ) : (
          bars.map(({ seg, leftPct, widthPct }, i) => {
            const fill = kindColor(seg.kind, tokens.dark);
            return (
              <div
                key={`${seg.start}-${i}`}
                title={`${seg.kind} · ${formatAbsolute(seg.start)} → ${formatAbsolute(
                  seg.end,
                )} · ${formatDuration(seg.end - seg.start)}`}
                onMouseEnter={() =>
                  setHover({ seg, xPct: leftPct + widthPct / 2 })
                }
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: `${leftPct}%`,
                  width: `${widthPct}%`,
                  background: fill,
                  borderRight: `1px solid ${tokens.panel}`,
                  boxSizing: "border-box",
                  cursor: "default",
                }}
              />
            );
          })
        )}

        {nowFrac !== null && (
          <div
            title="now"
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${nowFrac * 100}%`,
              width: 2,
              marginLeft: -1,
              background: tokens.accent,
              opacity: 0.8,
              pointerEvents: "none",
            }}
          />
        )}

        {hover && (
          <div
            style={{
              position: "absolute",
              left: `${hover.xPct}%`,
              bottom: LANE_HEIGHT + 4,
              transform: "translateX(-50%)",
              background: tokens.bg,
              color: tokens.text,
              border: `1px solid ${tokens.border}`,
              borderRadius: 6,
              padding: "4px 8px",
              fontSize: 11,
              whiteSpace: "nowrap",
              pointerEvents: "none",
              zIndex: 2,
              boxShadow: "0 2px 6px rgba(0,0,0,0.25)",
            }}
          >
            <strong>{hover.seg.kind}</strong> ·{" "}
            {formatAbsolute(hover.seg.start)} → {formatAbsolute(hover.seg.end)}{" "}
            · {formatDuration(hover.seg.end - hover.seg.start)}
          </div>
        )}
      </div>

      {/* Axis */}
      <div
        style={{
          position: "relative",
          height: 16,
          marginTop: 2,
          fontSize: 10,
          color: tokens.subtext,
        }}
      >
        {ticks.map((tick) => {
          const leftPct = timeToFraction(tick.t, span) * 100;
          return (
            <span
              key={tick.t}
              style={{
                position: "absolute",
                left: `${leftPct}%`,
                transform: "translateX(-50%)",
                whiteSpace: "nowrap",
              }}
            >
              {tick.label}
            </span>
          );
        })}
      </div>

    </div>
  );
}

function Centered({
  tokens,
  children,
}: {
  tokens: ThemeTokens;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 12,
        color: tokens.subtext,
      }}
    >
      {children}
    </div>
  );
}
