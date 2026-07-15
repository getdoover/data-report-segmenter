/**
 * Pure timeline math for the single-lane Gantt + brush + date-range picker.
 *
 * Everything here is side-effect-free and unit-tested (`node --test`), so the
 * SVG/div presentation layers (GanttTimeline / TimelineBrush / DateRangePicker)
 * stay dumb. No `Date.now()` is called inside these functions — callers pass a
 * `now` so tests are deterministic.
 *
 *  - segment assembly: raw closed messages + the open current_segment into a
 *    normalised, time-sorted, back-to-back `Segment[]` (gap/overlap-tolerant:
 *    each segment ends where the next begins; the last/open one ends at `now`);
 *  - time <-> fraction/px mapping within a Timespan, and nice axis ticks;
 *  - a deterministic kind -> colour assignment (None is muted/neutral);
 *  - brush window math: full extent + selection window px <-> Timespan;
 *  - relative Timespan presets (24h / 7d / 30d).
 */

import dayjs from "dayjs";

import { NONE_KIND, type Timespan } from "./types.ts";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

/** Default history window the timeline fetches/shows: ~30 days. */
export const DEFAULT_FETCH_WINDOW_MS = 30 * DAY_MS;

/** Minimum brush selection width, in px, so the window stays grabbable. */
export const MIN_WINDOW_PX = 24;

/** An assembled, back-to-back timeline segment (epoch ms bounds). */
export interface Segment {
  kind: string;
  start: number;
  end: number;
}

/**
 * A raw segment before chaining: a closed segment carries its recorded end;
 * the open segment carries `end: null` (meaning "runs to now").
 */
export interface RawSegment {
  kind: string;
  start: number;
  end: number | null;
}

/** Minimal shape of a `tag_values` message as read by the widget. */
export interface SegmentMessageLike {
  data?: {
    record_type?: string;
    kind?: string;
    start_ts?: number;
    end_ts?: number;
  } | null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Pull the closed-segment records out of a raw `tag_values` message list.
 * Ignores every non-segment message (sensor diffs etc.). Malformed records are
 * skipped rather than throwing.
 */
export function extractClosedSegments(
  messages: SegmentMessageLike[] | undefined,
): RawSegment[] {
  if (!Array.isArray(messages)) {
    return [];
  }
  const out: RawSegment[] = [];
  for (const msg of messages) {
    const d = msg?.data;
    if (!d || d.record_type !== "segment") {
      continue;
    }
    if (
      typeof d.kind !== "string" ||
      d.kind === "" ||
      !isFiniteNumber(d.start_ts)
    ) {
      continue;
    }
    out.push({
      kind: d.kind,
      start: d.start_ts,
      end: isFiniteNumber(d.end_ts) ? d.end_ts : null,
    });
  }
  return out;
}

/**
 * Assemble the display timeline: sort by start, then chain each segment to the
 * next one's start so the lane is strictly back-to-back (one kind active at any
 * instant — no gaps, no overlaps). The final segment ends at its recorded end,
 * or `now` when it is the open one (`end: null`). Zero/negative-width segments
 * (duplicate starts) are dropped.
 */
export function assembleSegments(raw: RawSegment[], now: number): Segment[] {
  const valid = raw.filter((r) => isFiniteNumber(r.start));
  const sorted = valid.slice().sort((a, b) => {
    if (a.start !== b.start) {
      return a.start - b.start;
    }
    // On a tie, an open segment (end null) sorts last.
    const ae = a.end === null ? Infinity : a.end;
    const be = b.end === null ? Infinity : b.end;
    return ae - be;
  });

  const out: Segment[] = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const cur = sorted[i];
    const isLast = i === sorted.length - 1;
    const rawEnd = isLast
      ? cur.end === null
        ? now
        : cur.end
      : sorted[i + 1].start;
    const end = Math.max(cur.start, rawEnd);
    if (end > cur.start) {
      out.push({ kind: cur.kind, start: cur.start, end });
    }
  }
  return out;
}

/** Earliest start / latest end across the assembled segments, else null. */
export function segmentsExtent(segments: Segment[]): Timespan | null {
  if (segments.length === 0) {
    return null;
  }
  let after = segments[0].start;
  let before = segments[0].end;
  for (const seg of segments) {
    if (seg.start < after) {
      after = seg.start;
    }
    if (seg.end > before) {
      before = seg.end;
    }
  }
  return { after, before };
}

function spanWidth(span: Timespan): number {
  return span.before - span.after;
}

/** Clip each segment to `[span.after, span.before]`; drop empties/out-of-range. */
export function clampSegmentsToSpan(
  segments: Segment[],
  span: Timespan,
): Segment[] {
  const out: Segment[] = [];
  for (const seg of segments) {
    const start = Math.max(seg.start, span.after);
    const end = Math.min(seg.end, span.before);
    if (end > start) {
      out.push({ kind: seg.kind, start, end });
    }
  }
  return out;
}

/** Position of `t` within `span` as a 0..1 fraction (clamped). */
export function timeToFraction(t: number, span: Timespan): number {
  const w = spanWidth(span);
  if (w <= 0) {
    return 0;
  }
  const f = (t - span.after) / w;
  return f < 0 ? 0 : f > 1 ? 1 : f;
}

/** Inverse of {@link timeToFraction}: a 0..1 fraction back to epoch ms. */
export function fractionToTime(f: number, span: Timespan): number {
  const clamped = f < 0 ? 0 : f > 1 ? 1 : f;
  return span.after + clamped * spanWidth(span);
}

export interface AxisTick {
  t: number;
  label: string;
}

// Nice step ladder (ms). generateAxisTicks picks the smallest step that keeps
// the tick count at/under the target.
const TICK_STEPS_MS = [
  HOUR_MS,
  2 * HOUR_MS,
  3 * HOUR_MS,
  6 * HOUR_MS,
  12 * HOUR_MS,
  DAY_MS,
  2 * DAY_MS,
  7 * DAY_MS,
  14 * DAY_MS,
  30 * DAY_MS,
];

/**
 * Axis ticks on nice hour/day boundaries within `span`. Aligns to the local
 * hour (sub-day steps) or local day (>= day steps) via dayjs, then walks the
 * step until past `span.before`. Labels show time-of-day for sub-day steps,
 * else day + month.
 */
export function generateAxisTicks(span: Timespan, maxTicks = 6): AxisTick[] {
  const w = spanWidth(span);
  if (w <= 0 || maxTicks < 1) {
    return [];
  }
  let step = TICK_STEPS_MS[TICK_STEPS_MS.length - 1];
  for (const candidate of TICK_STEPS_MS) {
    if (w / candidate <= maxTicks) {
      step = candidate;
      break;
    }
  }

  const subDay = step < DAY_MS;
  const first = dayjs(span.after).startOf(subDay ? "hour" : "day");
  const fmt = subDay ? "HH:mm" : "D MMM";

  const ticks: AxisTick[] = [];
  let t = first.valueOf();
  // Advance to the first boundary at/after the span start.
  while (t < span.after) {
    t += step;
  }
  // Guard against pathological loops on absurd spans.
  let guard = 0;
  while (t <= span.before && guard < 1000) {
    ticks.push({ t, label: dayjs(t).format(fmt) });
    t += step;
    guard += 1;
  }
  return ticks;
}

/**
 * Deterministic categorical palette. Chosen to stay legible as a bar fill in
 * both light and dark themes. Order is stable; assignment is by a content hash
 * of the kind string, so a kind keeps its colour regardless of the set of
 * other kinds present or render order.
 */
export const KIND_PALETTE = [
  "#2563eb",
  "#16a34a",
  "#d97706",
  "#9333ea",
  "#dc2626",
  "#0891b2",
  "#db2777",
  "#65a30d",
  "#4f46e5",
  "#ea580c",
];

/** FNV-1a 32-bit hash — small, deterministic, no deps. */
function hashString(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

/** Stable palette index for a kind (ignores the None special-case). */
export function kindColorIndex(kind: string): number {
  return hashString(kind) % KIND_PALETTE.length;
}

/** Colour for a kind: None is a muted neutral, others hash into the palette. */
export function kindColor(kind: string, dark: boolean): string {
  if (kind === NONE_KIND) {
    return dark ? "#565c66" : "#c2c8d0";
  }
  return KIND_PALETTE[kindColorIndex(kind)];
}

/** Pick black/white text for a hex fill by relative luminance (WCAG-ish). */
export function barTextColor(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) {
    return "#ffffff";
  }
  const n = parseInt(m[1], 16);
  const r = (n >> 16) & 0xff;
  const g = (n >> 8) & 0xff;
  const b = n & 0xff;
  // Perceived luminance (sRGB weights, no gamma — good enough for a swatch).
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? "#1a1d21" : "#ffffff";
}

/**
 * Distinct kinds present in a segment list, in first-seen order — for the
 * legend.
 */
export function legendKinds(segments: Segment[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const seg of segments) {
    if (!seen.has(seg.kind)) {
      seen.add(seg.kind);
      out.push(seg.kind);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Brush window math
// ---------------------------------------------------------------------------

export interface WindowPx {
  left: number;
  width: number;
}

/** Selection Timespan -> pixel window over a brush track of `trackWidth` px. */
export function spanToWindowPx(
  extent: Timespan,
  span: Timespan,
  trackWidth: number,
  minWindowPx = MIN_WINDOW_PX,
): WindowPx {
  if (trackWidth <= 0) {
    return { left: 0, width: 0 };
  }
  const leftFrac = timeToFraction(span.after, extent);
  const rightFrac = timeToFraction(span.before, extent);
  let left = leftFrac * trackWidth;
  let width = Math.max((rightFrac - leftFrac) * trackWidth, minWindowPx);
  if (left + width > trackWidth) {
    left = Math.max(0, trackWidth - width);
    width = Math.min(width, trackWidth - left);
  }
  return { left, width };
}

/** Pixel window over a `trackWidth` track -> selection Timespan within extent. */
export function windowPxToSpan(
  extent: Timespan,
  left: number,
  width: number,
  trackWidth: number,
  minWindowPx = MIN_WINDOW_PX,
): Timespan {
  if (trackWidth <= 0) {
    return { after: extent.after, before: extent.before };
  }
  const w = Math.max(minWindowPx, Math.min(width, trackWidth));
  const clampedLeft = Math.max(0, Math.min(left, trackWidth - w));
  const after = fractionToTime(clampedLeft / trackWidth, extent);
  const before = fractionToTime((clampedLeft + w) / trackWidth, extent);
  return { after, before };
}

/** Clamp a Timespan inside `extent`, keeping at least `minMs` of width. */
export function clampSpanToExtent(
  span: Timespan,
  extent: Timespan,
  minMs: number,
): Timespan {
  const extW = spanWidth(extent);
  const width = Math.max(minMs, Math.min(span.before - span.after, extW));
  let after = Math.max(
    extent.after,
    Math.min(span.after, extent.before - width),
  );
  let before = after + width;
  if (before > extent.before) {
    before = extent.before;
    after = before - width;
  }
  return { after, before };
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

export type PresetKey = "24h" | "7d" | "30d";

export const PRESETS: { key: PresetKey; label: string; ms: number }[] = [
  { key: "24h", label: "24h", ms: DAY_MS },
  { key: "7d", label: "7d", ms: 7 * DAY_MS },
  { key: "30d", label: "30d", ms: 30 * DAY_MS },
];

/** A relative Timespan ending at `now` for a preset key. */
export function presetSpan(preset: PresetKey, now: number): Timespan {
  const found = PRESETS.find((p) => p.key === preset);
  const ms = found ? found.ms : DAY_MS;
  return { after: now - ms, before: now };
}

/** Default visible window: the last `days` (default 7) ending at `now`. */
export function defaultTimespan(now: number, days = 7): Timespan {
  return { after: now - days * DAY_MS, before: now };
}
