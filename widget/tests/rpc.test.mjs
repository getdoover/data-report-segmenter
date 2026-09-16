/**
 * RPC request builders + error extraction. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  buildReportRequest,
  buildSwitchRequest,
  errorMessage,
} from "../src/lib/rpc.ts";

test("buildSwitchRequest carries kind + client_ts", () => {
  assert.deepEqual(buildSwitchRequest("Pipeline A", 1789000000000), {
    kind: "Pipeline A",
    client_ts: 1789000000000,
  });
});

test("buildSwitchRequest defaults client_ts to now", () => {
  const before = Date.now();
  const req = buildSwitchRequest("None");
  assert.equal(req.kind, "None");
  assert.ok(req.client_ts >= before && req.client_ts <= Date.now());
});

test("buildReportRequest carries kind + range + time zone", () => {
  assert.deepEqual(buildReportRequest("A", 1000, 2000, "Asia/Riyadh"), {
    kind: "A",
    start_ts: 1000,
    end_ts: 2000,
    tz: "Asia/Riyadh",
  });
  // No zone available -> field omitted (processor falls back to UTC).
  assert.deepEqual(buildReportRequest("A", 1000, 2000, null), {
    kind: "A",
    start_ts: 1000,
    end_ts: 2000,
  });
});

test("buildReportRequest defaults to the browser time zone", () => {
  assert.equal(
    buildReportRequest("A", 1000, 2000).tz,
    Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
});

test("errorMessage handles Error, string, nested pydoover status", () => {
  assert.equal(errorMessage(new Error("boom")), "boom");
  assert.equal(errorMessage("nope"), "nope");
  // pydoover error status.message = {code, message}
  assert.equal(
    errorMessage({ message: { code: "BAD_KIND", message: "unknown kind" } }),
    "unknown kind",
  );
  assert.equal(errorMessage({ message: "flat" }), "flat");
  assert.equal(errorMessage(undefined), "Something went wrong");
});
