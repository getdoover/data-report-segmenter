/**
 * Generate-report flow. Fires the `generate_report` RPC but — per the pinned
 * contract — does NOT depend on the RPC response (30s JS wait vs 300s lambda).
 * Instead it correlates the fired request to its `segment_reports` job message
 * (matchReportMessage) and tracks that message's lifecycle
 * Generating -> Complete/Failed. On Complete it exposes the attachment's signed
 * URL and attempts a one-shot auto-download.
 *
 * `messages` must be an update-aware view (useReportsWatch) — a plain
 * useChannelMessages list never sees the terminal update_message flip. As a
 * second safety net, while THIS hook's own request is non-terminal (including
 * "Submitting", where even the create event may have been dropped) it calls
 * `refetchMessages` every ~10s.
 */
import { type ReportDownload, type ReportMessage } from "../lib/reports.ts";
import { type ReportStatus } from "../lib/types.ts";
export type ActiveReportStatus = ReportStatus | "Submitting";
export interface ActiveReport {
    kind: string;
    startTs: number;
    endTs: number;
    status: ActiveReportStatus;
    message: ReportMessage | null;
    download: ReportDownload | null;
    error: string | null;
}
export interface GenerateReportResult {
    generate: (kind: string, startTs: number, endTs: number) => void;
    active: ActiveReport | null;
    fireError: string | null;
}
export declare function useGenerateReport(agentId: string | undefined, appKey: string, messages: ReportMessage[], refetchMessages?: () => void): GenerateReportResult;
