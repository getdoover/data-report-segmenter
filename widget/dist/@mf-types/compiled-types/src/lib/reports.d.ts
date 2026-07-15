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
import { type ReportRecord, type ReportStatus } from "./types.ts";
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
export declare function isReportMessage(msg: ReportMessage): boolean;
/** Normalise the free-text status into a known lifecycle state. */
export declare function classifyReport(msg: ReportMessage): ReportStatus;
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
export declare function matchReportMessage(messages: ReportMessage[], params: MatchParams): ReportMessage | null;
/** All report messages, newest first (for the "recent reports" list). */
export declare function sortReportsDesc(messages: ReportMessage[]): ReportMessage[];
export interface ReportDownload {
    url: string;
    filename: string;
}
/**
 * Download target for a completed report: the first attachment's signed URL,
 * with a filename (attachment's own, else derived to match the processor).
 */
export declare function reportDownload(msg: ReportMessage): ReportDownload | null;
