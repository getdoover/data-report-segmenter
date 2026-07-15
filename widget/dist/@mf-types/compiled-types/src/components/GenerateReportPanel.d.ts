/**
 * Compact "Generate Report" panel: kind dropdown (report option rules — always
 * includes "None"), start/end datetime-local pickers (default: last 7 days),
 * and a Generate button. Shows the active job's lifecycle
 * (Submitting -> Generating -> Complete/Failed) with a download button on
 * completion. Fire/watch logic lives in useGenerateReport; this stays dumb.
 */
import type { ThemeTokens } from "../lib/theme.ts";
import type { ActiveReport } from "../hooks/useGenerateReport.ts";
export declare function GenerateReportPanel({ tokens, options, active, fireError, onGenerate, }: {
    tokens: ThemeTokens;
    options: string[];
    active: ActiveReport | null;
    fireError: string | null;
    onGenerate: (kind: string, startTs: number, endTs: number) => void;
}): import("react").JSX.Element;
