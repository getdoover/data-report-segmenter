/**
 * Recent reports list — a cheap win from the same segment_reports channel we
 * already watch. Each completed report links to its signed-URL CSV.
 */

import { formatAbsolute } from "../lib/format.ts";
import {
  classifyReport,
  reportDownload,
  type ReportMessage,
} from "../lib/reports.ts";
import type { ThemeTokens } from "../lib/theme.ts";

export function ReportList({
  tokens,
  reports,
  limit = 5,
}: {
  tokens: ThemeTokens;
  reports: ReportMessage[];
  limit?: number;
}) {
  const rows = reports.slice(0, limit);
  if (rows.length === 0) {
    return null;
  }

  return (
    <div style={{ marginTop: 10 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: tokens.subtext,
          marginBottom: 6,
        }}
      >
        Recent reports
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.map((msg) => {
          const status = classifyReport(msg);
          const download = status === "Complete" ? reportDownload(msg) : null;
          const kind = typeof msg.data.kind === "string" ? msg.data.kind : "?";
          const start =
            typeof msg.data.start_ts === "number"
              ? formatAbsolute(msg.data.start_ts)
              : "—";
          const end =
            typeof msg.data.end_ts === "number"
              ? formatAbsolute(msg.data.end_ts)
              : "—";
          return (
            <div
              key={msg.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
                fontSize: 12,
                padding: "4px 8px",
                background: tokens.panel,
                border: `1px solid ${tokens.border}`,
                borderRadius: 6,
              }}
            >
              <span style={{ color: tokens.text }}>
                {kind}{" "}
                <span style={{ color: tokens.subtext }}>
                  {start} → {end}
                </span>
              </span>
              {download ? (
                <a
                  href={download.url}
                  download={download.filename}
                  style={{ color: tokens.accent }}
                >
                  Download
                </a>
              ) : (
                <span
                  style={{
                    color: status === "Failed" ? tokens.danger : tokens.subtext,
                  }}
                >
                  {status === "Unknown" ? "—" : status}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
