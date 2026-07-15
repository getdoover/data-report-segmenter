/**
 * segment_reports message matching + lifecycle. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  classifyReport,
  isReportMessage,
  matchReportMessage,
  reportDownload,
  sortReportsDesc,
} from "../src/lib/reports.ts";

function reportMsg(id, ts, data, attachments) {
  return { id, timestamp: ts, data, attachments };
}

const base = { record_type: "report", kind: "A", start_ts: 1000, end_ts: 2000 };

test("isReportMessage discriminates on record_type", () => {
  assert.equal(isReportMessage(reportMsg("1", 1, base)), true);
  assert.equal(
    isReportMessage(reportMsg("2", 1, { record_type: "segment" })),
    false,
  );
});

test("classifyReport normalises status", () => {
  assert.equal(classifyReport(reportMsg("1", 1, { ...base, status: "Generating" })), "Generating");
  assert.equal(classifyReport(reportMsg("1", 1, { ...base, status: "Complete" })), "Complete");
  assert.equal(classifyReport(reportMsg("1", 1, { ...base, status: "Failed" })), "Failed");
  assert.equal(classifyReport(reportMsg("1", 1, { ...base })), "Unknown");
});

test("matchReportMessage finds the newest matching job at/after submit", () => {
  const submittedAt = 5000;
  const messages = [
    reportMsg("old", 4000, { ...base, status: "Complete" }), // before submit
    reportMsg("a", 5200, { ...base, status: "Generating" }),
    reportMsg("b", 5300, { ...base, status: "Complete" }),
    reportMsg("other", 5400, { ...base, kind: "B", status: "Complete" }), // wrong kind
  ];
  const match = matchReportMessage(messages, {
    kind: "A",
    startTs: 1000,
    endTs: 2000,
    submittedAt,
  });
  assert.equal(match.id, "b");
});

test("matchReportMessage tolerates clock skew below the window", () => {
  const messages = [reportMsg("a", 4990, { ...base, status: "Generating" })];
  const match = matchReportMessage(messages, {
    kind: "A",
    startTs: 1000,
    endTs: 2000,
    submittedAt: 5000,
    skewMs: 15000,
  });
  assert.equal(match.id, "a");
});

test("matchReportMessage returns null with no param match", () => {
  const messages = [reportMsg("a", 6000, { ...base, end_ts: 9999 })];
  const match = matchReportMessage(messages, {
    kind: "A",
    startTs: 1000,
    endTs: 2000,
    submittedAt: 5000,
  });
  assert.equal(match, null);
});

test("reportDownload prefers attachment filename, else derives", () => {
  const withName = reportMsg("a", 1, base, [
    { url: "https://s3/x", filename: "custom.csv" },
  ]);
  assert.deepEqual(reportDownload(withName), {
    url: "https://s3/x",
    filename: "custom.csv",
  });

  const noName = reportMsg(
    "b",
    1,
    { ...base, start_ts: Date.UTC(2026, 6, 8), end_ts: Date.UTC(2026, 6, 15) },
    [{ url: "https://s3/y" }],
  );
  assert.equal(
    reportDownload(noName).filename,
    "data_report_segmenter_A_20260708-20260715.csv",
  );
});

test("reportDownload null when no usable attachment", () => {
  assert.equal(reportDownload(reportMsg("a", 1, base, [])), null);
  assert.equal(reportDownload(reportMsg("a", 1, base)), null);
});

test("sortReportsDesc filters to reports, newest first", () => {
  const messages = [
    reportMsg("a", 100, base),
    reportMsg("seg", 200, { record_type: "segment" }),
    reportMsg("b", 300, base),
  ];
  const sorted = sortReportsDesc(messages);
  assert.deepEqual(
    sorted.map((m) => m.id),
    ["b", "a"],
  );
});
