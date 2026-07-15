/**
 * Live-updating, assembled segment history for the Gantt timeline.
 *
 * Wraps the two Doover channels the timeline reads:
 *  - `tag_values` MESSAGES for the closed segments (append-only records with
 *    `record_type: "segment"`, `{kind, start_ts, end_ts}` — other tag_values
 *    messages are sensor diffs and are filtered out client-side);
 *  - the `tag_values` AGGREGATE for the open `current_segment` (`{kind,
 *    start_ts}`), rendered as a bar running to `now`.
 *
 * Live behaviour (mirrors useReportsWatch's intent): closed segments arrive as
 * message CREATE events (a switch appends the just-closed segment), which
 * `useChannelMessages({ liveUpdates: true })` follows; the new open segment
 * arrives as an aggregate update on `useAgentChannel`. Segment messages are
 * append-only (never updated in place), so — unlike segment_reports — no
 * MessageUpdate overlay is needed here; both sources are already live.
 *
 * The fetch lower bound is a snowflake id derived once (on mount) from
 * `now - rangeMs` via doover-js `generateSnowflakeIdAtTime`, so the query walks
 * back exactly the configured window (default ~30 days) instead of the whole
 * channel, and its key stays stable across renders (no `now` churn).
 */

import { useMemo, useState } from "react";
import { useAgentChannel, useChannelMessages } from "doover-js/react";
import { generateSnowflakeIdAtTime } from "doover-js";

import { extractCurrentSegment } from "../lib/config.ts";
import {
  assembleSegments,
  extractClosedSegments,
  segmentsExtent,
  type RawSegment,
  type Segment,
} from "../lib/timeline.ts";
import type { Timespan } from "../lib/types.ts";

/** Payload shape of a closed-segment `tag_values` message (all optional). */
interface SegmentRecord {
  record_type?: string;
  kind?: string;
  start_ts?: number;
  end_ts?: number;
}

export interface SegmentHistoryResult {
  /** Assembled, back-to-back, time-sorted segments (open one runs to `now`). */
  segments: Segment[];
  /** Data extent across all segments, or null when there are none. */
  extent: Timespan | null;
  /** True while the first page is still loading with nothing to show yet. */
  loading: boolean;
}

const PAGE_LIMIT = 100;

export function useSegmentHistory(
  agentId: string | undefined,
  appKey: string,
  rangeMs: number,
  now: number,
): SegmentHistoryResult {
  // Stable lower-bound cursor: computed once so the query key doesn't churn as
  // `now` advances each render.
  const [afterId] = useState(() =>
    generateSnowflakeIdAtTime(Date.now() - rangeMs),
  );

  const query = useChannelMessages<SegmentRecord>(
    { agentId, channelName: "tag_values" },
    {
      fields: ["record_type", "kind", "start_ts", "end_ts"],
      liveUpdates: true,
      after: afterId,
      autoPaginate: true,
      limit: PAGE_LIMIT,
    },
  );

  const { data: tagValues } = useAgentChannel(agentId, "tag_values");
  const current = useMemo(
    () => extractCurrentSegment(tagValues, appKey),
    [tagValues, appKey],
  );

  const segments = useMemo(() => {
    const raw: RawSegment[] = extractClosedSegments(query.messages);
    if (current.kind !== null && current.startTs !== null) {
      raw.push({ kind: current.kind, start: current.startTs, end: null });
    }
    return assembleSegments(raw, now);
  }, [query.messages, current.kind, current.startTs, now]);

  const extent = useMemo(() => segmentsExtent(segments), [segments]);

  const loading = query.isLoading && segments.length === 0;

  return { segments, extent, loading };
}
