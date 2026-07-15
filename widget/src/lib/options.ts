/**
 * Dropdown option-list derivation. Two contexts with different "None" rules
 * (PLAN.md "Widget behaviour" 3 + 5):
 *
 *  - Switch dropdown: "None" appears iff show_none_segment — EXCEPT when
 *    segment_kinds is empty, where options are ["None"] regardless.
 *  - Report dropdown: ALWAYS includes "None" (reports over None periods are
 *    legitimate).
 *
 * Both preserve config order, dedupe, and can ensure the currently-selected
 * kind is present (so a stale/removed kind still renders as selected instead
 * of silently snapping to another value).
 */

import { NONE_KIND } from "./types.ts";

function dedupe(kinds: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of kinds) {
    if (!seen.has(k)) {
      seen.add(k);
      out.push(k);
    }
  }
  return out;
}

/**
 * Options for the header switch dropdown.
 *
 * @param segmentKinds configured kinds (never includes the implicit "None")
 * @param showNone     deployment_config `show_none_segment`
 * @param ensureKind   current kind to guarantee is selectable (optional)
 */
export function deriveSegmentOptions(
  segmentKinds: string[],
  showNone: boolean,
  ensureKind?: string | null,
): string[] {
  const clean = dedupe(segmentKinds.filter((k) => k !== ""));

  let options: string[];
  if (clean.length === 0) {
    // Empty config -> "None" is used regardless of show_none_segment.
    options = [NONE_KIND];
  } else {
    options = showNone ? [...clean, NONE_KIND] : [...clean];
  }

  if (ensureKind && ensureKind !== "" && !options.includes(ensureKind)) {
    // A current kind not in the option set (e.g. config changed after the
    // segment opened) must still be shown as selected.
    options = [ensureKind, ...options];
  }
  return dedupe(options);
}

/**
 * Options for the Generate Report dropdown — "None" is always offered.
 */
export function deriveReportOptions(
  segmentKinds: string[],
  ensureKind?: string | null,
): string[] {
  const clean = dedupe(segmentKinds.filter((k) => k !== ""));
  let options = clean.length === 0 ? [NONE_KIND] : [...clean, NONE_KIND];
  if (ensureKind && ensureKind !== "" && !options.includes(ensureKind)) {
    options = [ensureKind, ...options];
  }
  return dedupe(options);
}
