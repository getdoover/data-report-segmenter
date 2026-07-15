/**
 * Dropdown option-list derivation. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  deriveReportOptions,
  deriveSegmentOptions,
} from "../src/lib/options.ts";

test("switch: kinds without None when show_none is false", () => {
  assert.deepEqual(deriveSegmentOptions(["A", "B"], false), ["A", "B"]);
});

test("switch: appends None when show_none is true", () => {
  assert.deepEqual(deriveSegmentOptions(["A", "B"], true), ["A", "B", "None"]);
});

test("switch: empty kinds -> ['None'] regardless of show_none", () => {
  assert.deepEqual(deriveSegmentOptions([], false), ["None"]);
  assert.deepEqual(deriveSegmentOptions([], true), ["None"]);
});

test("switch: ensureKind prepends a current kind not in the set", () => {
  assert.deepEqual(deriveSegmentOptions(["A", "B"], false, "Legacy"), [
    "Legacy",
    "A",
    "B",
  ]);
});

test("switch: ensureKind already present is not duplicated", () => {
  assert.deepEqual(deriveSegmentOptions(["A", "B"], false, "A"), ["A", "B"]);
});

test("switch: dedupes repeated kinds", () => {
  assert.deepEqual(deriveSegmentOptions(["A", "A", "B"], false), ["A", "B"]);
});

test("report: always includes None", () => {
  assert.deepEqual(deriveReportOptions(["A", "B"]), ["A", "B", "None"]);
  assert.deepEqual(deriveReportOptions([]), ["None"]);
});

test("report: does not duplicate None when a kind is literally 'None'", () => {
  assert.deepEqual(deriveReportOptions(["None", "A"]), ["None", "A"]);
});

test("report: ensureKind prepends unknown current kind", () => {
  assert.deepEqual(deriveReportOptions(["A"], "Legacy"), ["Legacy", "A", "None"]);
});
