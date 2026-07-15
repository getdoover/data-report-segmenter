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

/** True when the report has reached a terminal lifecycle state. */
export function isTerminalReport(msg: ReportMessage): boolean {
  const status = classifyReport(msg);
  return status === "Complete" || status === "Failed";
}

/**
 * Live-update overlay: the latest gateway MessageCreate/MessageUpdate event
 * per message id, maintained by the widget's channel subscription.
 *
 * Needed because doover-js `useChannelMessages` subscribes with only
 * `{ onMessage }` — MessageUpdate events are dropped and the query is
 * staleTime-Infinity, so the processor's status flip
 * (Generating -> Complete/Failed via update_message) never reaches the list.
 */
export type ReportOverlay = Record<string, ReportMessage>;

/**
 * Merge a live-updated message over its base-list counterpart.
 *
 * Payload choice: a TERMINAL side wins (a stale "Generating" create event must
 * never mask a refetched "Complete", and vice versa a live "Complete" update
 * must beat a stale REST page); on a tie the update (newer event) wins.
 * Attachments: the chosen side's, unless empty and the other side has some
 * (a MessageUpdate event may not carry the CSV attachment the REST refetch
 * does — never lose it).
 */
export function mergeReportMessage(
  base: ReportMessage,
  update: ReportMessage,
): ReportMessage {
  const chooseUpdate = isTerminalReport(update) || !isTerminalReport(base);
  const chosen = chooseUpdate ? update : base;
  const other = chooseUpdate ? base : update;
  const attachments =
    chosen.attachments && chosen.attachments.length > 0
      ? chosen.attachments
      : other.attachments ?? [];
  return { ...chosen, attachments };
}

/**
 * Apply the overlay to the base message list (id-keyed):
 *  - an overlay entry matching a base message REPLACES it (mergeReportMessage
 *    semantics: data + attachments, terminal-wins);
 *  - an overlay entry with an UNKNOWN id is APPENDED — a create event that
 *    raced (or was dropped before) the REST seed must still surface.
 * Order of the base list is preserved; consumers sort/filter downstream.
 */
export function applyMessageOverlay(
  messages: ReportMessage[],
  overlay: ReportOverlay,
): ReportMessage[] {
  const ids = Object.keys(overlay);
  if (ids.length === 0) {
    return messages;
  }
  const seen = new Set<string>();
  const out = messages.map((msg) => {
    seen.add(msg.id);
    const updated = overlay[msg.id];
    return updated ? mergeReportMessage(msg, updated) : msg;
  });
  for (const id of ids) {
    if (!seen.has(id)) {
      out.push(overlay[id]);
    }
  }
  return out;
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
