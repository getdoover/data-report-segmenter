/**
 * Pure extraction of this install's config + open segment from the raw
 * Doover channel aggregates the widget reads via doover-js.
 *
 *   deployment_config -> applications[appKey] -> { segment_kinds,
 *                        show_none_segment, segments_label }
 *   tag_values        -> [appKey].current_segment -> { kind, start_ts }
 *
 * No hooks, no I/O — unit-testable. Never throws on malformed input; returns
 * defaults / placeholders instead (the widget must render before data loads).
 */

import {
  DEFAULT_SEGMENTS_LABEL,
  type AppConfig,
  type CurrentSegment,
} from "./types.ts";

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asNonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/** Coerce an unknown into a clean list of non-empty string kinds. */
export function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: string[] = [];
  for (const item of value) {
    if (typeof item === "string" && item !== "") {
      out.push(item);
    }
  }
  return out;
}

/**
 * Read `deployment_config.applications[appKey]` into a defaulted AppConfig.
 * Missing/malformed values fall back to: [] kinds, showNone false,
 * "Segment" label.
 */
export function extractAppConfig(
  deploymentConfig: unknown,
  appKey: string,
): AppConfig {
  const applications = asRecord(asRecord(deploymentConfig).applications);
  const block = asRecord(applications[appKey]);
  return {
    segmentKinds: asStringList(block.segment_kinds),
    showNone: block.show_none_segment === true,
    segmentsLabel:
      asNonEmptyString(block.segments_label) ?? DEFAULT_SEGMENTS_LABEL,
    // Default ON: only an explicit `false` hides the timeline.
    showTimeline: block.show_timeline_chart !== false,
  };
}

/**
 * Read `tag_values[appKey].current_segment` into a CurrentSegment. Returns
 * null fields when absent so callers render the em-dash placeholder rather
 * than crashing on undefined.
 */
export function extractCurrentSegment(
  tagValues: unknown,
  appKey: string,
): CurrentSegment {
  const block = asRecord(asRecord(tagValues)[appKey]);
  const seg = asRecord(block.current_segment);
  return {
    kind: asNonEmptyString(seg.kind),
    startTs: asFiniteNumber(seg.start_ts),
  };
}
