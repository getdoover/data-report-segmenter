/**
 * Pure timeline math. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  assembleSegments,
  barTextColor,
  clampSegmentsToSpan,
  clampSpanToExtent,
  defaultTimespan,
  extractClosedSegments,
  fractionToTime,
  generateAxisTicks,
  kindColor,
  kindColorIndex,
  legendKinds,
  presetSpan,
  segmentsExtent,
  spanToWindowPx,
  timeToFraction,
  windowPxToSpan,
  MIN_WINDOW_PX,
} from "../src/lib/timeline.ts";

const DAY = 24 * 60 * 60 * 1000;

test("extractClosedSegments keeps only segment records", () => {
  const raw = [
    { data: { record_type: "segment", kind: "A", start_ts: 100, end_ts: 200 } },
    { data: { record_type: "sensor_diff", value: 3 } },
    { data: { record_type: "segment", kind: "B", start_ts: 200 } },
    { data: { record_type: "segment", kind: "", start_ts: 300, end_ts: 400 } },
    { data: null },
    {},
  ];
  const out = extractClosedSegments(raw);
  assert.deepEqual(out, [
    { kind: "A", start: 100, end: 200 },
    { kind: "B", start: 200, end: null },
  ]);
});

test("extractClosedSegments tolerates non-arrays", () => {
  assert.deepEqual(extractClosedSegments(undefined), []);
  assert.deepEqual(extractClosedSegments(null), []);
});

test("assembleSegments chains back-to-back, open runs to now", () => {
  const now = 1000;
  const segs = assembleSegments(
    [
      { kind: "A", start: 0, end: 300 },
      { kind: "B", start: 400, end: null }, // open
      { kind: "None", start: 300, end: 380 },
    ],
    now,
  );
  // Sorted by start: A(0), None(300), B(400 open). Ends chain to next start;
  // last (open) ends at now — recorded ends are ignored except the last.
  assert.deepEqual(segs, [
    { kind: "A", start: 0, end: 300 },
    { kind: "None", start: 300, end: 400 },
    { kind: "B", start: 400, end: 1000 },
  ]);
});

test("assembleSegments drops zero-width duplicates and closes on recorded end", () => {
  const now = 5000;
  const segs = assembleSegments(
    [
      { kind: "A", start: 100, end: 100 }, // dup start with B -> zero width, dropped
      { kind: "B", start: 100, end: 900 }, // last, closed -> uses recorded end
    ],
    now,
  );
  assert.deepEqual(segs, [{ kind: "B", start: 100, end: 900 }]);
});

test("assembleSegments handles a lone open segment", () => {
  assert.deepEqual(
    assembleSegments([{ kind: "None", start: 200, end: null }], 800),
    [{ kind: "None", start: 200, end: 800 }],
  );
  assert.deepEqual(assembleSegments([], 800), []);
});

test("segmentsExtent spans min start to max end", () => {
  assert.equal(segmentsExtent([]), null);
  assert.deepEqual(
    segmentsExtent([
      { kind: "A", start: 100, end: 300 },
      { kind: "B", start: 300, end: 900 },
    ]),
    { after: 100, before: 900 },
  );
});

test("clampSegmentsToSpan clips and drops out-of-range", () => {
  const span = { after: 200, before: 500 };
  const out = clampSegmentsToSpan(
    [
      { kind: "A", start: 0, end: 250 },
      { kind: "B", start: 250, end: 600 },
      { kind: "C", start: 600, end: 700 },
    ],
    span,
  );
  assert.deepEqual(out, [
    { kind: "A", start: 200, end: 250 },
    { kind: "B", start: 250, end: 500 },
  ]);
});

test("timeToFraction / fractionToTime round-trip and clamp", () => {
  const span = { after: 1000, before: 3000 };
  assert.equal(timeToFraction(2000, span), 0.5);
  assert.equal(timeToFraction(0, span), 0); // clamped
  assert.equal(timeToFraction(9999, span), 1); // clamped
  assert.equal(fractionToTime(0.5, span), 2000);
  assert.equal(fractionToTime(2, span), 3000); // clamped
  // degenerate span
  assert.equal(timeToFraction(5, { after: 10, before: 10 }), 0);
});

test("generateAxisTicks stay in range, increase, and are bounded in count", () => {
  const span = {
    after: Date.UTC(2026, 6, 1, 3, 20),
    before: Date.UTC(2026, 6, 8, 3, 20),
  };
  const ticks = generateAxisTicks(span, 6);
  assert.ok(ticks.length >= 2 && ticks.length <= 6, `count ${ticks.length}`);
  for (let i = 0; i < ticks.length; i += 1) {
    assert.ok(ticks[i].t >= span.after && ticks[i].t <= span.before);
    assert.equal(typeof ticks[i].label, "string");
    assert.ok(ticks[i].label.length > 0);
    if (i > 0) {
      assert.ok(ticks[i].t > ticks[i - 1].t);
    }
  }
});

test("generateAxisTicks picks sub-day step for short spans", () => {
  const span = {
    after: Date.UTC(2026, 6, 1, 0, 0),
    before: Date.UTC(2026, 6, 1, 12, 0),
  };
  const ticks = generateAxisTicks(span, 6);
  assert.ok(ticks.length >= 2);
  // labels look like HH:mm
  assert.match(ticks[0].label, /^\d{2}:\d{2}$/);
});

test("generateAxisTicks degenerate span -> empty", () => {
  assert.deepEqual(generateAxisTicks({ after: 5, before: 5 }), []);
});

test("kindColorIndex is deterministic and in range", () => {
  assert.equal(kindColorIndex("Pipeline A"), kindColorIndex("Pipeline A"));
  const idx = kindColorIndex("Pipeline A");
  assert.ok(idx >= 0 && idx < 10);
});

test("kindColor: None is neutral, others come from the palette", () => {
  assert.equal(kindColor("None", true), "#565c66");
  assert.equal(kindColor("None", false), "#c2c8d0");
  assert.match(kindColor("Cleaning", false), /^#[0-9a-f]{6}$/);
  assert.notEqual(kindColor("Cleaning", false), kindColor("None", false));
});

test("barTextColor chooses contrast by luminance", () => {
  assert.equal(barTextColor("#000000"), "#ffffff");
  assert.equal(barTextColor("#ffffff"), "#1a1d21");
  assert.equal(barTextColor("#2563eb"), "#ffffff");
  assert.equal(barTextColor("not-a-color"), "#ffffff");
});

test("legendKinds returns first-seen distinct kinds", () => {
  assert.deepEqual(
    legendKinds([
      { kind: "A", start: 0, end: 1 },
      { kind: "B", start: 1, end: 2 },
      { kind: "A", start: 2, end: 3 },
    ]),
    ["A", "B"],
  );
});

test("spanToWindowPx <-> windowPxToSpan round-trip", () => {
  const extent = { after: 0, before: 1000 };
  const span = { after: 200, before: 600 };
  const track = 500;
  const { left, width } = spanToWindowPx(extent, span, track);
  assert.ok(Math.abs(left - 100) < 1e-6);
  assert.ok(Math.abs(width - 200) < 1e-6);
  const back = windowPxToSpan(extent, left, width, track);
  assert.ok(Math.abs(back.after - 200) < 1e-6);
  assert.ok(Math.abs(back.before - 600) < 1e-6);
});

test("spanToWindowPx enforces minimum width and keeps window on-track", () => {
  const extent = { after: 0, before: 1000 };
  const track = 500;
  // a razor-thin span near the right edge
  const { left, width } = spanToWindowPx(
    extent,
    { after: 999, before: 1000 },
    track,
  );
  assert.equal(width, MIN_WINDOW_PX);
  assert.ok(left + width <= track);
});

test("windowPxToSpan clamps px into the track", () => {
  const extent = { after: 0, before: 1000 };
  const track = 500;
  const s = windowPxToSpan(extent, -50, 100, track);
  assert.equal(s.after, 0);
  const s2 = windowPxToSpan(extent, 480, 100, track); // overflow right
  assert.equal(s2.before, 1000);
});

test("clampSpanToExtent keeps min width and stays inside extent", () => {
  const extent = { after: 0, before: 1000 };
  const s = clampSpanToExtent({ after: -100, before: 50 }, extent, 200);
  assert.equal(s.after, 0);
  assert.equal(s.before, 200);
  const s2 = clampSpanToExtent({ after: 950, before: 1100 }, extent, 200);
  assert.equal(s2.before, 1000);
  assert.equal(s2.after, 800);
  // a span wider than the extent collapses to the whole extent
  const s3 = clampSpanToExtent({ after: 950, before: 2000 }, extent, 200);
  assert.equal(s3.after, 0);
  assert.equal(s3.before, 1000);
});

test("presetSpan builds relative windows from now", () => {
  const now = 1_000_000_000_000;
  assert.deepEqual(presetSpan("24h", now), { after: now - DAY, before: now });
  assert.deepEqual(presetSpan("7d", now), {
    after: now - 7 * DAY,
    before: now,
  });
  assert.deepEqual(presetSpan("30d", now), {
    after: now - 30 * DAY,
    before: now,
  });
});

test("defaultTimespan is the last N days", () => {
  const now = 2_000_000_000_000;
  assert.deepEqual(defaultTimespan(now), { after: now - 7 * DAY, before: now });
  assert.deepEqual(defaultTimespan(now, 30), {
    after: now - 30 * DAY,
    before: now,
  });
});
