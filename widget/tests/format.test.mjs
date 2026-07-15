/**
 * Filename + date helpers. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  defaultReportRange,
  formatAbsolute,
  formatDuration,
  formatRelativeSince,
  fromDatetimeLocalValue,
  reportFilename,
  sanitizeSegment,
  toDatetimeLocalValue,
  yyyymmddUtc,
} from "../src/lib/format.ts";

test("sanitizeSegment keeps safe chars, collapses the rest", () => {
  assert.equal(sanitizeSegment("Pipeline A/B"), "Pipeline_A_B");
  assert.equal(sanitizeSegment("  weird**name  "), "weird_name");
  assert.equal(sanitizeSegment("///"), "none");
});

test("yyyymmddUtc formats UTC date", () => {
  // 2026-07-15T00:00:00Z
  assert.equal(yyyymmddUtc(Date.UTC(2026, 6, 15)), "20260715");
});

test("reportFilename matches processor pattern", () => {
  const fn = reportFilename(
    "data_report_segmenter",
    "Pipeline A",
    Date.UTC(2026, 6, 8),
    Date.UTC(2026, 6, 15),
  );
  assert.equal(fn, "data_report_segmenter_Pipeline_A_20260708-20260715.csv");
});

test("datetime-local round-trips through local wall time", () => {
  const ms = new Date(2026, 6, 15, 9, 30).getTime();
  const value = toDatetimeLocalValue(ms);
  assert.match(value, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  assert.equal(fromDatetimeLocalValue(value), ms);
});

test("fromDatetimeLocalValue rejects empty/invalid", () => {
  assert.equal(fromDatetimeLocalValue(""), null);
  assert.equal(fromDatetimeLocalValue("not-a-date"), null);
});

test("defaultReportRange spans 7 days ending now", () => {
  const now = new Date(2026, 6, 15, 12, 0).getTime();
  const range = defaultReportRange(now);
  assert.equal(range.endTs, now);
  assert.equal(range.startTs, now - 7 * 24 * 60 * 60 * 1000);
  assert.equal(range.endValue, toDatetimeLocalValue(now));
});

test("formatRelativeSince buckets", () => {
  const now = 1_000_000_000_000;
  assert.equal(formatRelativeSince(null, now), "—");
  assert.equal(formatRelativeSince(now, now), "just now");
  assert.equal(formatRelativeSince(now - 5 * 60000, now), "5m ago");
  assert.equal(formatRelativeSince(now - 3 * 3600000, now), "3h ago");
  assert.equal(formatRelativeSince(now - 2 * 86400000, now), "2d ago");
  assert.equal(formatRelativeSince(now + 60000, now), "just now");
});

test("formatDuration buckets seconds/minutes/hours/days", () => {
  assert.equal(formatDuration(0), "0s");
  assert.equal(formatDuration(-5), "0s");
  assert.equal(formatDuration(45 * 1000), "45s");
  assert.equal(formatDuration(12 * 60 * 1000), "12m");
  assert.equal(formatDuration(3 * 3600 * 1000), "3h");
  assert.equal(formatDuration((3 * 3600 + 20 * 60) * 1000), "3h 20m");
  assert.equal(formatDuration(2 * 86400 * 1000), "2d");
  assert.equal(formatDuration((2 * 86400 + 5 * 3600) * 1000), "2d 5h");
});

test("formatAbsolute renders em-dash for null", () => {
  assert.equal(formatAbsolute(null), "—");
  assert.match(formatAbsolute(Date.now()), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
});
