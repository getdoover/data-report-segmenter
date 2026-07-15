/**
 * Header row: `"{segments_label}: {current kind}"` with the switch dropdown to
 * the right and a subtle "since ..." line. Missing data renders the em-dash
 * placeholder rather than crashing.
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
