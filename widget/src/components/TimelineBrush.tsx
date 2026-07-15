/**
 * Overview strip beneath the main Gantt: a miniature of the FULL segment
 * history (over `extent`) with a draggable + resizable selection window that
 * drives the visible Timespan — Doover's `CustomBrush` equivalent, built from
 * plain divs + pointer events (no charting lib).
 *
 * Window geometry is rendered in percentages (so it scales with the container)
 * but drag maths run in pixels via lib/timeline.ts's
 * spanToWindowPx / windowPxToSpan, which clamp to the track and enforce a
 * minimum grabbable width.
 */

import { useRef } from "react";

import type { ThemeTokens } from "../lib/theme.ts";
import {
  kindColor,
  spanToWindowPx,
  timeToFraction,
  windowPxToSpan,
  MIN_WINDOW_PX,
  type Segment,
} from "../lib/timeline.ts";
import type { Timespan } from "../lib/types.ts";

const STRIP_HEIGHT = 28;
const HANDLE_WIDTH = 8;

type DragMode = "move" | "resize-l" | "resize-r";

interface DragState {
  mode: DragMode;
  startClientX: number;
  trackWidth: number;
  origLeft: number;
  origWidth: number;
}

export function TimelineBrush({
  tokens,
  segments,
  extent,
  value,
  onChange,
}: {
  tokens: ThemeTokens;
  segments: Segment[];
  extent: Timespan;
  value: Timespan;
  onChange: (span: Timespan) => void;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragState | null>(null);

  const leftFrac = timeToFraction(value.after, extent);
  const rightFrac = timeToFraction(value.before, extent);
  const leftPct = leftFrac * 100;
  const widthPct = Math.max((rightFrac - leftFrac) * 100, 0);

  const onPointerMove = (e: PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) {
      return;
    }
    const delta = e.clientX - drag.startClientX;
    const right = drag.origLeft + drag.origWidth;
    let nextLeft = drag.origLeft;
    let nextWidth = drag.origWidth;
    if (drag.mode === "move") {
      nextLeft = drag.origLeft + delta;
    } else if (drag.mode === "resize-l") {
      nextLeft = Math.min(drag.origLeft + delta, right - MIN_WINDOW_PX);
      nextWidth = right - nextLeft;
    } else {
      nextWidth = Math.max(MIN_WINDOW_PX, drag.origWidth + delta);
    }
    onChange(
      windowPxToSpan(
        extent,
        nextLeft,
        nextWidth,
        drag.trackWidth,
        MIN_WINDOW_PX,
      ),
    );
  };

  const endDrag = () => {
    dragRef.current = null;
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", endDrag);
  };

  const startDrag = (mode: DragMode) => (e: React.PointerEvent) => {
    const track = trackRef.current;
    if (!track) {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    const rect = track.getBoundingClientRect();
    const { left, width } = spanToWindowPx(extent, value, rect.width);
    dragRef.current = {
      mode,
      startClientX: e.clientX,
      trackWidth: rect.width,
      origLeft: left,
      origWidth: width,
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", endDrag);
  };

  // Click on the track background: recentre the window there.
  const onTrackClick = (e: React.MouseEvent) => {
    if (dragRef.current) {
      return;
    }
    const track = trackRef.current;
    if (!track) {
      return;
    }
    const rect = track.getBoundingClientRect();
    const { width } = spanToWindowPx(extent, value, rect.width);
    const clickX = e.clientX - rect.left;
    onChange(
      windowPxToSpan(
        extent,
        clickX - width / 2,
        width,
        rect.width,
        MIN_WINDOW_PX,
      ),
    );
  };

  return (
    <div
      ref={trackRef}
      onMouseDown={onTrackClick}
      style={{
        position: "relative",
        height: STRIP_HEIGHT,
        background: tokens.panel,
        border: `1px solid ${tokens.border}`,
        borderRadius: 6,
        overflow: "hidden",
        cursor: "crosshair",
      }}
    >
      {/* Mini history */}
      {segments.map((seg, i) => {
        const l = timeToFraction(seg.start, extent) * 100;
        const w =
          (timeToFraction(seg.end, extent) -
            timeToFraction(seg.start, extent)) *
          100;
        if (w <= 0) {
          return null;
        }
        return (
          <div
            key={`${seg.start}-${i}`}
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${l}%`,
              width: `${w}%`,
              background: kindColor(seg.kind, tokens.dark),
              opacity: 0.55,
            }}
          />
        );
      })}

      {/* Dim outside the selection */}
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          left: 0,
          width: `${leftPct}%`,
          background: tokens.dark
            ? "rgba(0,0,0,0.45)"
            : "rgba(255,255,255,0.5)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          left: `${leftPct + widthPct}%`,
          right: 0,
          background: tokens.dark
            ? "rgba(0,0,0,0.45)"
            : "rgba(255,255,255,0.5)",
          pointerEvents: "none",
        }}
      />

      {/* Selection window */}
      <div
        onPointerDown={startDrag("move")}
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          left: `${leftPct}%`,
          width: `${widthPct}%`,
          border: `1px solid ${tokens.accent}`,
          background: "transparent",
          boxSizing: "border-box",
          cursor: "grab",
        }}
      >
        <Handle
          side="left"
          tokens={tokens}
          onPointerDown={startDrag("resize-l")}
        />
        <Handle
          side="right"
          tokens={tokens}
          onPointerDown={startDrag("resize-r")}
        />
      </div>
    </div>
  );
}

function Handle({
  side,
  tokens,
  onPointerDown,
}: {
  side: "left" | "right";
  tokens: ThemeTokens;
  onPointerDown: (e: React.PointerEvent) => void;
}) {
  return (
    <div
      onPointerDown={onPointerDown}
      style={{
        position: "absolute",
        top: 0,
        bottom: 0,
        [side]: -1,
        width: HANDLE_WIDTH,
        background: tokens.accent,
        opacity: 0.9,
        cursor: "ew-resize",
        borderRadius: 2,
      }}
    />
  );
}
