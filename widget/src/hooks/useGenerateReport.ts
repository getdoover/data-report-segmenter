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

import { useCallback, useEffect, useRef, useState } from "react";
import { useSendRpc } from "doover-js/react";

import { buildReportRequest, errorMessage } from "../lib/rpc.ts";
import {
  classifyReport,
  matchReportMessage,
  reportDownload,
  type ReportDownload,
  type ReportMessage,
} from "../lib/reports.ts";
import {
  RPC_CHANNEL,
  type GenerateReportRequest,
  type ReportStatus,
} from "../lib/types.ts";

interface ActiveRequest {
  kind: string;
  startTs: number;
  endTs: number;
  submittedAt: number;
}

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

/** Best-effort browser download of a (possibly cross-origin) signed URL. */
function triggerDownload(url: string, filename: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  a.target = "_blank";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

const REQUEST_POLL_INTERVAL_MS = 10000;

export function useGenerateReport(
  agentId: string | undefined,
  appKey: string,
  messages: ReportMessage[],
  refetchMessages?: () => void,
): GenerateReportResult {
  const rpc = useSendRpc<GenerateReportRequest, unknown>(
    { agentId, channelName: RPC_CHANNEL },
    { method: "generate_report", app_key: appKey },
  );

  const [request, setRequest] = useState<ActiveRequest | null>(null);
  const [fireError, setFireError] = useState<string | null>(null);
  const downloadedIds = useRef<Set<string>>(new Set());

  const generate = useCallback(
    (kind: string, startTs: number, endTs: number) => {
      if (!agentId) {
        setFireError("No agent context — cannot generate report.");
        return;
      }
      setFireError(null);
      setRequest({ kind, startTs, endTs, submittedAt: Date.now() });
      const commandId = `report-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      // Fire-and-forget: we watch segment_reports, not the RPC response.
      rpc
        .mutateAsync({
          commandId,
          request: buildReportRequest(kind, startTs, endTs),
        })
        .catch((err: unknown) => setFireError(errorMessage(err)));
    },
    [agentId, rpc],
  );

  // Correlate the fired request to its job message.
  const matched =
    request === null
      ? null
      : matchReportMessage(messages, {
          kind: request.kind,
          startTs: request.startTs,
          endTs: request.endTs,
          submittedAt: request.submittedAt,
        });

  const download = matched ? reportDownload(matched) : null;

  // Poll while our own request is non-terminal (Submitting = no job message
  // matched yet, Generating = matched but not flipped) so a dropped WS event
  // can't strand the panel. Refetch fn is read through a ref so an unstable
  // closure identity doesn't reset the interval each render.
  const refetchRef = useRef(refetchMessages);
  refetchRef.current = refetchMessages;
  const requestSettled =
    request === null || (matched !== null && classifyReport(matched) !== "Generating");
  useEffect(() => {
    if (requestSettled) {
      return;
    }
    const timer = setInterval(() => {
      refetchRef.current?.();
    }, REQUEST_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [requestSettled]);

  // Auto-download once when a matched report completes with an attachment.
  useEffect(() => {
    if (
      matched &&
      classifyReport(matched) === "Complete" &&
      download &&
      !downloadedIds.current.has(matched.id)
    ) {
      downloadedIds.current.add(matched.id);
      triggerDownload(download.url, download.filename);
    }
  }, [matched, download]);

  const active: ActiveReport | null =
    request === null
      ? null
      : {
          kind: request.kind,
          startTs: request.startTs,
          endTs: request.endTs,
          status: matched ? classifyReport(matched) : "Submitting",
          message: matched,
          download,
          error:
            matched && classifyReport(matched) === "Failed"
              ? matched.data.error ?? "Report generation failed"
              : null,
        };

  return { generate, active, fireError };
}
