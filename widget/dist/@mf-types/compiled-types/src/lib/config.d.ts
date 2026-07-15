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
import { type AppConfig, type CurrentSegment } from "./types.ts";
/** Coerce an unknown into a clean list of non-empty string kinds. */
export declare function asStringList(value: unknown): string[];
/**
 * Read `deployment_config.applications[appKey]` into a defaulted AppConfig.
 * Missing/malformed values fall back to: [] kinds, showNone false,
 * "Segment" label.
 */
export declare function extractAppConfig(deploymentConfig: unknown, appKey: string): AppConfig;
/**
 * Read `tag_values[appKey].current_segment` into a CurrentSegment. Returns
 * null fields when absent so callers render the em-dash placeholder rather
 * than crashing on undefined.
 */
export declare function extractCurrentSegment(tagValues: unknown, appKey: string): CurrentSegment;
