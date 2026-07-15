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

import { useEffect, useMemo, useState } from "react";
import {
  useChannelMessages,
  useChannelSubscription,
} from "doover-js/react";

import {
  applyMessageOverlay,
  classifyReport,
  isReportMessage,
  type ReportMessage,
  type ReportOverlay,
} from "../lib/reports.ts";
import { REPORTS_CHANNEL, type ReportRecord } from "../lib/types.ts";

const POLL_INTERVAL_MS = 10000;

export interface ReportsWatchResult {
  /** Base list with live create/update events merged in. */
  messages: ReportMessage[];
  /** Refetch the underlying messages query (for callers' own fallbacks). */
  refetch: () => void;
}

export function useReportsWatch(agentId: string | undefined): ReportsWatchResult {
  const identifier = { agentId, channelName: REPORTS_CHANNEL };
  const query = useChannelMessages<ReportRecord>(identifier, {
    limit: 25,
    liveUpdates: true,
  });

  const [overlay, setOverlay] = useState<ReportOverlay>({});
  useChannelSubscription(agentId ? identifier : undefined, {
    onMessage: (msg) =>
      setOverlay((current) => ({
        ...current,
        [msg.id]: msg as unknown as ReportMessage,
      })),
    onMessageUpdate: (msg) =>
      setOverlay((current) => ({
        ...current,
        [msg.id]: msg as unknown as ReportMessage,
      })),
  });

  const messages = useMemo(
    () =>
      applyMessageOverlay(
        query.messages as unknown as ReportMessage[],
        overlay,
      ),
    [query.messages, overlay],
  );

  // Polling fallback: only while a visible report is still generating.
  const { refetch } = query;
  const hasNonTerminal = useMemo(
    () =>
      messages.some(
        (msg) => isReportMessage(msg) && classifyReport(msg) === "Generating",
      ),
    [messages],
  );
  useEffect(() => {
    if (!hasNonTerminal) {
      return;
    }
    const timer = setInterval(() => {
      void refetch();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [hasNonTerminal, refetch]);

  return { messages, refetch: () => void refetch() };
}
