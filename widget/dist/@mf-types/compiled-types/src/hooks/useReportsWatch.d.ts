/**
 * Update-aware live view of the `segment_reports` channel.
 *
 * doover-js `useChannelMessages` subscribes with only `{ onMessage }`
 * (doover-js dist react/useChannelMessages.js:69) — it receives message-CREATE
 * events but silently drops message-UPDATE events, and its query is
 * staleTime-Infinity. The report processor creates the job message as
 * "Generating" then flips it to "Complete"/"Failed" (attaching the CSV) via
 * update_message on the SAME id, so a plain useChannelMessages view would show
 * "generating…" forever.
 *
 * Fix, per layer:
 *  1. `useChannelMessages` still seeds/pages the history and follows creates;
 *  2. a `useChannelSubscription` with BOTH onMessage and onMessageUpdate
 *     maintains an id-keyed overlay of the latest gateway event per message
 *     (doover-js dist react/useChannelSubscription.js:22-26 wires
 *     onMessageUpdate through to the gateway subscription);
 *  3. `applyMessageOverlay` (pure, unit-tested) merges the overlay over the
 *     base list — terminal status wins, attachments are never lost;
 *  4. a modest polling fallback refetches the messages query every ~10s ONLY
 *     while some visible report is still non-terminal, so a dropped WS event
 *     cannot strand the UI.
 */
import { type ReportMessage } from "../lib/reports.ts";
export interface ReportsWatchResult {
    /** Base list with live create/update events merged in. */
    messages: ReportMessage[];
    /** Refetch the underlying messages query (for callers' own fallbacks). */
    refetch: () => void;
}
export declare function useReportsWatch(agentId: string | undefined): ReportsWatchResult;
