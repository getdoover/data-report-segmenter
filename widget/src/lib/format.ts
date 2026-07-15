/**
 * Date/label formatting helpers — all pure and unit-tested.
 *
 *  - reportFilename: mirrors the processor's `{app_name}_{kind}_{YYYYMMDD}-
 *    {YYYYMMDD}.csv` (UTC) so the widget's fallback filename matches.
 *  - datetime-local <input> value <-> epoch-ms conversion (local wall time).
 *  - defaultReportRange: last 7 days.
 *  - formatRelativeSince / formatAbsolute: the subtle "since ..." on the header.
 */

const EM_DASH = "—";
const DAY_MS = 24 * 60 * 60 * 1000;

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** Filesystem-safe: keep [A-Za-z0-9._-], collapse the rest to "_". */
export function sanitizeSegment(value: string): string {
  const cleaned = value.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  return cleaned === "" ? "none" : cleaned;
}

/** UTC YYYYMMDD for a filename date part. */
export function yyyymmddUtc(ms: number): string {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}${pad2(d.getUTCMonth() + 1)}${pad2(
    d.getUTCDate(),
  )}`;
}

/** `{app_name}_{kind}_{YYYYMMDD}-{YYYYMMDD}.csv`, sanitised. */
export function reportFilename(
  appName: string,
  kind: string,
  startTs: number,
  endTs: number,
): string {
  return `${sanitizeSegment(appName)}_${sanitizeSegment(kind)}_${yyyymmddUtc(
    startTs,
  )}-${yyyymmddUtc(endTs)}.csv`;
}

/** epoch-ms -> "YYYY-MM-DDTHH:mm" in LOCAL wall time for a datetime-local input. */
export function toDatetimeLocalValue(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(
    d.getDate(),
  )}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/**
 * datetime-local input value -> epoch ms (interpreted as local wall time).
 * Returns null for an empty/invalid value.
 */
export function fromDatetimeLocalValue(value: string): number | null {
  if (!value) {
    return null;
  }
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : null;
}

export interface ReportRange {
  startTs: number;
  endTs: number;
  startValue: string;
  endValue: string;
}

/** Sensible default report window: the last 7 days ending now. */
export function defaultReportRange(now: number = Date.now()): ReportRange {
  const startTs = now - 7 * DAY_MS;
  return {
    startTs,
    endTs: now,
    startValue: toDatetimeLocalValue(startTs),
    endValue: toDatetimeLocalValue(now),
  };
}

/** Short relative age, e.g. "just now", "5m ago", "3h ago", "2d ago". */
export function formatRelativeSince(
  startTs: number | null,
  now: number = Date.now(),
): string {
  if (startTs === null || !Number.isFinite(startTs)) {
    return EM_DASH;
  }
  const diff = now - startTs;
  if (diff < 0) {
    return "just now";
  }
  const mins = Math.floor(diff / 60000);
  if (mins < 1) {
    return "just now";
  }
  if (mins < 60) {
    return `${mins}m ago`;
  }
  const hours = Math.floor(mins / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/** Local, human-readable absolute time (for the `title`/tooltip). */
export function formatAbsolute(ts: number | null): string {
  if (ts === null || !Number.isFinite(ts)) {
    return EM_DASH;
  }
  const d = new Date(ts);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(
    d.getDate(),
  )} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}
