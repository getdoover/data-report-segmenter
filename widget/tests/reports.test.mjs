/**
 * segment_reports message matching + lifecycle. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  applyMessageOverlay,
  classifyReport,
  isReportMessage,
  isTerminalReport,
  matchReportMessage,
  mergeReportMessage,
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

test("isTerminalReport: Complete/Failed only", () => {
  assert.equal(isTerminalReport(reportMsg("1", 1, { ...base, status: "Complete" })), true);
  assert.equal(isTerminalReport(reportMsg("1", 1, { ...base, status: "Failed" })), true);
  assert.equal(isTerminalReport(reportMsg("1", 1, { ...base, status: "Generating" })), false);
  assert.equal(isTerminalReport(reportMsg("1", 1, { ...base })), false);
});

test("mergeReportMessage: live terminal update beats stale Generating base", () => {
  const stale = reportMsg("a", 100, { ...base, status: "Generating" });
  const update = reportMsg("a", 100, { ...base, status: "Complete" }, [
    { url: "https://s3/x", filename: "r.csv" },
  ]);
  const merged = mergeReportMessage(stale, update);
  assert.equal(merged.data.status, "Complete");
  assert.equal(merged.attachments[0].url, "https://s3/x");
});

test("mergeReportMessage: refetched terminal base beats stale Generating overlay", () => {
  // create event (Generating) pinned in the overlay; polling refetch later
  // returns Complete — the terminal side must win regardless of direction.
  const overlayCreate = reportMsg("a", 100, { ...base, status: "Generating" });
  const refetchedBase = reportMsg("a", 100, { ...base, status: "Complete" }, [
    { url: "https://s3/x" },
  ]);
  const merged = mergeReportMessage(refetchedBase, overlayCreate);
  assert.equal(merged.data.status, "Complete");
  assert.equal(merged.attachments[0].url, "https://s3/x");
});

test("mergeReportMessage: non-terminal tie prefers the update", () => {
  const oldGen = reportMsg("a", 100, { ...base, status: "Generating" });
  const newGen = reportMsg("a", 100, { ...base, status: "Generating", rows: 5 });
  assert.equal(mergeReportMessage(oldGen, newGen).data.rows, 5);
});

test("mergeReportMessage: attachments survive an update event without them", () => {
  // A MessageUpdate event may omit attachments the REST refetch carried.
  const withCsv = reportMsg("a", 100, { ...base, status: "Complete" }, [
    { url: "https://s3/x", filename: "r.csv" },
  ]);
  const bareUpdate = reportMsg("a", 100, { ...base, status: "Complete" }, []);
  const merged = mergeReportMessage(withCsv, bareUpdate);
  assert.equal(merged.attachments.length, 1);
  assert.equal(merged.attachments[0].url, "https://s3/x");
});

test("applyMessageOverlay replaces matching ids in place", () => {
  const messages = [
    reportMsg("a", 100, { ...base, status: "Generating" }),
    reportMsg("b", 200, { ...base, status: "Complete" }),
  ];
  const overlay = {
    a: reportMsg("a", 100, { ...base, status: "Complete" }, [
      { url: "https://s3/a" },
    ]),
  };
  const merged = applyMessageOverlay(messages, overlay);
  assert.equal(merged.length, 2);
  assert.equal(merged[0].id, "a");
  assert.equal(merged[0].data.status, "Complete");
  assert.equal(merged[1].data.status, "Complete");
});

test("applyMessageOverlay appends unknown ids (documented policy)", () => {
  const messages = [reportMsg("a", 100, base)];
  const overlay = { fresh: reportMsg("fresh", 300, { ...base, status: "Generating" }) };
  const merged = applyMessageOverlay(messages, overlay);
  assert.deepEqual(
    merged.map((m) => m.id),
    ["a", "fresh"],
  );
});

test("applyMessageOverlay with empty overlay returns the same list", () => {
  const messages = [reportMsg("a", 100, base)];
  assert.equal(applyMessageOverlay(messages, {}), messages);
});

test("overlay flow end-to-end: matcher + download see the terminal update", () => {
  // The exact bug scenario: create arrives (Generating), update flips it.
  const submittedAt = 5000;
  const created = reportMsg("job", 5100, { ...base, status: "Generating" });
  const updated = reportMsg("job", 5100, { ...base, status: "Complete" }, [
    { url: "https://s3/csv", filename: "out.csv" },
  ]);
  const merged = applyMessageOverlay([created], { job: updated });
  const match = matchReportMessage(merged, {
    kind: "A",
    startTs: 1000,
    endTs: 2000,
    submittedAt,
  });
  assert.equal(classifyReport(match), "Complete");
  assert.deepEqual(reportDownload(match), {
    url: "https://s3/csv",
    filename: "out.csv",
  });
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
