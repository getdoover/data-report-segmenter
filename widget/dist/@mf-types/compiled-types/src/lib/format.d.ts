/**
 * Date/label formatting helpers — all pure and unit-tested.
 *
 *  - reportFilename: mirrors the processor's `{app_name}_{kind}_{YYYYMMDD}-
 *    {YYYYMMDD}.csv` (UTC) so the widget's fallback filename matches.
 *  - datetime-local <input> value <-> epoch-ms conversion (local wall time).
 *  - defaultReportRange: last 7 days.
 *  - formatRelativeSince / formatAbsolute: the subtle "since ..." on the header.
 */
/** Filesystem-safe: keep [A-Za-z0-9._-], collapse the rest to "_". */
export declare function sanitizeSegment(value: string): string;
/** UTC YYYYMMDD for a filename date part. */
export declare function yyyymmddUtc(ms: number): string;
/** `{app_name}_{kind}_{YYYYMMDD}-{YYYYMMDD}.csv`, sanitised. */
export declare function reportFilename(appName: string, kind: string, startTs: number, endTs: number): string;
/** epoch-ms -> "YYYY-MM-DDTHH:mm" in LOCAL wall time for a datetime-local input. */
export declare function toDatetimeLocalValue(ms: number): string;
/**
 * datetime-local input value -> epoch ms (interpreted as local wall time).
 * Returns null for an empty/invalid value.
 */
export declare function fromDatetimeLocalValue(value: string): number | null;
export interface ReportRange {
    startTs: number;
    endTs: number;
    startValue: string;
    endValue: string;
}
/** Sensible default report window: the last 7 days ending now. */
export declare function defaultReportRange(now?: number): ReportRange;
/** Short relative age, e.g. "just now", "5m ago", "3h ago", "2d ago". */
export declare function formatRelativeSince(startTs: number | null, now?: number): string;
/** Local, human-readable absolute time (for the `title`/tooltip). */
export declare function formatAbsolute(ts: number | null): string;
