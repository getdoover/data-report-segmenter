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
/**
 * Options for the header switch dropdown.
 *
 * @param segmentKinds configured kinds (never includes the implicit "None")
 * @param showNone     deployment_config `show_none_segment`
 * @param ensureKind   current kind to guarantee is selectable (optional)
 */
export declare function deriveSegmentOptions(segmentKinds: string[], showNone: boolean, ensureKind?: string | null): string[];
/**
 * Options for the Generate Report dropdown — "None" is always offered.
 */
export declare function deriveReportOptions(segmentKinds: string[], ensureKind?: string | null): string[];
