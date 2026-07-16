/**
 * Config + open-segment extraction. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  asStringList,
  extractAppConfig,
  extractCurrentSegment,
} from "../src/lib/config.ts";

test("extractAppConfig reads the app block", () => {
  const cfg = extractAppConfig(
    {
      applications: {
        data_report_segmenter: {
          segment_kinds: ["Pipeline A", "Pipeline B"],
          show_none_segment: true,
          segments_label: "Batch",
        },
      },
    },
    "data_report_segmenter",
  );
  assert.deepEqual(cfg, {
    segmentKinds: ["Pipeline A", "Pipeline B"],
    showNone: true,
    segmentsLabel: "Batch",
    showTimeline: true,
  });
});

test("extractAppConfig returns defaults for missing/malformed data", () => {
  assert.deepEqual(extractAppConfig(undefined, "x"), {
    segmentKinds: [],
    showNone: false,
    segmentsLabel: "Segment",
    showTimeline: true,
  });
  assert.deepEqual(extractAppConfig({ applications: {} }, "x"), {
    segmentKinds: [],
    showNone: false,
    segmentsLabel: "Segment",
    showTimeline: true,
  });
});

test("extractAppConfig hides timeline only on explicit false", () => {
  assert.equal(
    extractAppConfig(
      { applications: { a: { show_timeline_chart: false } } },
      "a",
    ).showTimeline,
    false,
  );
});

test("extractAppConfig only treats explicit true as showNone", () => {
  const cfg = extractAppConfig(
    { applications: { a: { show_none_segment: "true" } } },
    "a",
  );
  assert.equal(cfg.showNone, false);
});

test("asStringList filters non-strings and empties", () => {
  assert.deepEqual(asStringList(["a", "", 1, null, "b"]), ["a", "b"]);
  assert.deepEqual(asStringList("nope"), []);
});

test("extractCurrentSegment reads kind + start_ts", () => {
  const seg = extractCurrentSegment(
    { data_report_segmenter: { current_segment: { kind: "None", start_ts: 1789000000000 } } },
    "data_report_segmenter",
  );
  assert.deepEqual(seg, { kind: "None", startTs: 1789000000000 });
});

test("extractCurrentSegment yields nulls when absent", () => {
  assert.deepEqual(extractCurrentSegment(undefined, "a"), {
    kind: null,
    startTs: null,
  });
  assert.deepEqual(extractCurrentSegment({ a: {} }, "a"), {
    kind: null,
    startTs: null,
  });
});

test("extractCurrentSegment rejects non-finite start_ts and empty kind", () => {
  const seg = extractCurrentSegment(
    { a: { current_segment: { kind: "", start_ts: "x" } } },
    "a",
  );
  assert.deepEqual(seg, { kind: null, startTs: null });
});
