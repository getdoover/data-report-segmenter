/**
 * segment_reports job-message helpers.
 *
 * The widget fires `generate_report` but does NOT depend on the RPC response
 * (30s JS wait vs 300s lambda) — instead it watches the segment_reports
 * channel for the job message reaching a terminal status. These pure helpers
 * do the correlation (match the fired request to its job message), lifecycle
 * classification, and download-target extraction.
 *
 * A minimal structural ReportMessage type is used instead of importing
 * doover-js's MessageStructure so this stays testable without the SDK.
 */

import {
  reportFilename,
  sanitizeSegment,
} from "./format.ts";
import { APP_NAME, type ReportRecord, type ReportStatus } from "./types.ts";

export interface ReportAttachment {
  url: string;
  filename?: string;
  content_type?: string | null;
  size?: number;
}

export interface ReportMessage {
  id: string;
  /** epoch ms (snowflake-derived) */
  timestamp: number;
  data: ReportRecord;
  attachments?: ReportAttachment[];
}

/** True when a message is a segment report record. */
export function isReportMessage(msg: ReportMessage): boolean {
  return msg?.data?.record_type === "report";
}

/** Normalise the free-text status into a known lifecycle state. */
export function classifyReport(msg: ReportMessage): ReportStatus {
  const status = msg?.data?.status;
  if (status === "Generating") {
    return "Generating";
  }
  if (status === "Complete") {
    return "Complete";
  }
  if (status === "Failed") {
    return "Failed";
  }
  return "Unknown";
}

export interface MatchParams {
  kind: string;
  startTs: number;
  endTs: number;
  /** client Date.now() at fire time — the message must be at/after this. */
  submittedAt: number;
  /** clock-skew tolerance (ms). */
  skewMs?: number;
}

/**
 * Find the job message produced by a just-fired generate_report request.
 *
 * The processor stamps its own `requested_ts`, so we correlate by the request
 * params (kind/start_ts/end_ts) and require the message to be at/after the
 * client submit time (minus skew). Returns the newest match, or null.
 */
export function matchReportMessage(
  messages: ReportMessage[],
  params: MatchParams,
): ReportMessage | null {
  const skew = params.skewMs ?? 15000;
  const floor = params.submittedAt - skew;
  let best: ReportMessage | null = null;
  for (const msg of messages) {
    if (!isReportMessage(msg)) {
      continue;
    }
    const d = msg.data;
    if (
      d.kind === params.kind &&
      d.start_ts === params.startTs &&
      d.end_ts === params.endTs &&
      typeof msg.timestamp === "number" &&
      msg.timestamp >= floor
    ) {
      if (best === null || msg.timestamp > best.timestamp) {
        best = msg;
      }
    }
  }
  return best;
}

/** All report messages, newest first (for the "recent reports" list). */
export function sortReportsDesc(messages: ReportMessage[]): ReportMessage[] {
  return messages
    .filter(isReportMessage)
    .slice()
    .sort((a, b) => b.timestamp - a.timestamp);
}

export interface ReportDownload {
  url: string;
  filename: string;
}

/**
 * Download target for a completed report: the first attachment's signed URL,
 * with a filename (attachment's own, else derived to match the processor).
 */
export function reportDownload(msg: ReportMessage): ReportDownload | null {
  const att = msg?.attachments?.find(
    (a) => typeof a?.url === "string" && a.url !== "",
  );
  if (!att) {
    return null;
  }
  const d = msg.data;
  const derived =
    typeof d.kind === "string" &&
    typeof d.start_ts === "number" &&
    typeof d.end_ts === "number"
      ? reportFilename(APP_NAME, d.kind, d.start_ts, d.end_ts)
      : `${sanitizeSegment(APP_NAME)}_report.csv`;
  return {
    url: att.url,
    filename:
      typeof att.filename === "string" && att.filename !== ""
        ? att.filename
        : derived,
  };
}
