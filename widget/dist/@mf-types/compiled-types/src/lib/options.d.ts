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
 * Initial dropdown value when the operator opens the switch editor.
 *
 * If the current kind is one of the options, start there (confirming without
 * changing it is then a harmless no-op). Otherwise — notably a hidden "None"
 * current segment with configured kinds — start on the FIRST option. This is
 * what makes the very first switch possible: a bare <select> fires no change
 * event when the wanted value is already the one shown, so relying on onChange
 * alone made the first configured kind unreachable. With an explicit draft +
 * Confirm, the first option is selectable on the first try.
 */
export declare function initialSwitchDraft(options: string[], currentKind: string | null): string;
/**
 * Options for the Generate Report dropdown — "None" is always offered.
 */
export declare function deriveReportOptions(segmentKinds: string[], ensureKind?: string | null): string[];
