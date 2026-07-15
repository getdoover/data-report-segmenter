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
/** True when the report has reached a terminal lifecycle state. */
export declare function isTerminalReport(msg: ReportMessage): boolean;
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
export declare function mergeReportMessage(base: ReportMessage, update: ReportMessage): ReportMessage;
/**
 * Apply the overlay to the base message list (id-keyed):
 *  - an overlay entry matching a base message REPLACES it (mergeReportMessage
 *    semantics: data + attachments, terminal-wins);
 *  - an overlay entry with an UNKNOWN id is APPENDED — a create event that
 *    raced (or was dropped before) the REST seed must still surface.
 * Order of the base list is preserved; consumers sort/filter downstream.
 */
export declare function applyMessageOverlay(messages: ReportMessage[], overlay: ReportOverlay): ReportMessage[];
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
