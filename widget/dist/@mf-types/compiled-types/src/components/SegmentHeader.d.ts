/**
 * Header row: `"{segments_label}: {current kind}"` with a "Change" button that
 * reveals the kind dropdown plus Confirm / Cancel, and a subtle "since ..."
 * line.
 *
 * Why a button + explicit Confirm rather than a bare always-visible dropdown:
 * a <select> only emits onChange when its value actually changes, so when the
 * current segment is "None" (hidden from the options) the first configured
 * kind is already the value shown and picking it fired nothing — making the
 * first switch impossible. A draft value committed on Confirm removes that
 * dependency (see initialSwitchDraft). It also guards against accidental
 * one-tap switches on a touchscreen panel.
 *
 * Missing data renders the implicit default ("None", per the spec: a freshly
 * deployed install has the None segment open) rather than crashing.
 */
import type { ThemeTokens } from "../lib/theme.ts";
export declare function SegmentHeader({ tokens, label, currentKind, startTs, options, pendingKind, disabled, error, now, onSelect, }: {
    tokens: ThemeTokens;
    label: string;
    currentKind: string | null;
    startTs: number | null;
    options: string[];
    pendingKind: string | null;
    disabled: boolean;
    error: string | null;
    now: number;
    onSelect: (kind: string) => void;
}): import("react").JSX.Element;
