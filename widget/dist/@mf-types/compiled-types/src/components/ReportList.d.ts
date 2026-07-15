/**
 * Recent reports list — a cheap win from the same segment_reports channel we
 * already watch. Each completed report links to its signed-URL CSV.
 */
import { type ReportMessage } from "../lib/reports.ts";
import type { ThemeTokens } from "../lib/theme.ts";
export declare function ReportList({ tokens, reports, limit, }: {
    tokens: ThemeTokens;
    reports: ReportMessage[];
    limit?: number;
}): import("react").JSX.Element | null;
