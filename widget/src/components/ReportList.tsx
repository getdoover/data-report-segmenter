/**
 * Recent reports list — a cheap win from the same segment_reports channel we
 * already watch. Each completed report is a blue download button whose white
 * label describes the segment kind + date range (the whole button downloads
 * the signed-URL CSV; no separate "Download" word).
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
    <div style={{ width: "25%", margin: "10px auto 0" }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: tokens.subtext,
          marginBottom: 6,
          textAlign: "center",
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
          const label = (
            <span>
              {kind} · {start} → {end}
            </span>
          );

          if (download) {
            // The whole row is the download control: blue button, white label.
            return (
              <a
                key={msg.id}
                href={download.url}
                download={download.filename}
                style={{
                  display: "block",
                  textAlign: "center",
                  fontSize: 12,
                  padding: "6px 8px",
                  background: tokens.accent,
                  color: tokens.accentText,
                  border: "none",
                  borderRadius: 6,
                  textDecoration: "none",
                }}
              >
                {label}
              </a>
            );
          }

          // Generating / Failed: not yet downloadable — a plain status chip.
          return (
            <div
              key={msg.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                fontSize: 12,
                padding: "6px 8px",
                background: tokens.panel,
                border: `1px solid ${tokens.border}`,
                borderRadius: 6,
                color: tokens.text,
              }}
            >
              {label}
              <span
                style={{
                  color: status === "Failed" ? tokens.danger : tokens.subtext,
                }}
              >
                {status === "Unknown" ? "—" : status}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
