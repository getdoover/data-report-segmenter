/**
 * Shared types for the data-report-segmenter widget.
 *
 * These mirror the pinned contract in .planning/PLAN.md — the tag_values
 * aggregate open-segment record, the deployment_config app block, the dv-rpc
 * request payloads, and the segment_reports job-message record.
 */

/** The always-present built-in segment kind. */
export const NONE_KIND = "None";

/** Default label rendered before the current kind. */
export const DEFAULT_SEGMENTS_LABEL = "Segment";

/** Default app_key when the host does not supply `uiElement.app_key`. */
export const DEFAULT_APP_KEY = "data_report_segmenter";

/** App name — used for report filenames. */
export const APP_NAME = "data_report_segmenter";

/** dv-rpc channel the processor subscribes to. */
export const RPC_CHANNEL = "dv-rpc";

/** Channel carrying the generated-report job messages. */
export const REPORTS_CHANNEL = "segment_reports";

/**
 * A visible time range, in epoch **milliseconds** — mirrors Doover's
 * `interpreterV2/types.ts` `Timespan` shape (the `{after, before}` variant the
 * Gantt/brush/picker all speak). `limit` is carried for wire-parity but unused
 * by the widget's client-side timeline math.
 */
export interface Timespan {
  /** epoch ms — inclusive lower bound of the visible window. */
  after: number;
  /** epoch ms — inclusive upper bound of the visible window. */
  before: number;
  /** optional page limit (Doover parity; unused here). */
  limit?: number;
}

/** Extracted, defaulted config for this install. */
export interface AppConfig {
  segmentKinds: string[];
  showNone: boolean;
  segmentsLabel: string;
  /** Whether the timeline Gantt chart + range selector is shown (default on). */
  showTimeline: boolean;
}

/** Open-segment pointer, from `tag_values.<appKey>.current_segment`. */
export interface CurrentSegment {
  kind: string | null;
  /** epoch ms */
  startTs: number | null;
}

/** `switch_segment` RPC request body. */
export interface SwitchSegmentRequest {
  kind: string;
  /** epoch ms of the client's switch instant, clamped server-side. */
  client_ts: number;
}

/** `generate_report` RPC request body. */
export interface GenerateReportRequest {
  kind: string;
  /** epoch ms */
  start_ts: number;
  /** epoch ms */
  end_ts: number;
}

export type ReportStatus = "Generating" | "Complete" | "Failed" | "Unknown";

/** Data payload of a `segment_reports` job message. */
export interface ReportRecord {
  record_type?: string;
  status?: string;
  kind?: string;
  start_ts?: number;
  end_ts?: number;
  requested_ts?: number;
  windows?: number;
  rows?: number;
  error?: string;
}
