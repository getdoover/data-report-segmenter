/**
 * dv-rpc request-payload builders + error-message extraction.
 *
 * These build the `request` object of the pydoover RPCManager wire shape.
 * doover-js `useSendRpc` wraps this as `{type:"rpc", method, request, app_key}`
 * (see rsbuild widget README "wire-shape decision") — we only own the inner
 * `request` here so the same builders are reused verbatim if the manual
 * useSendMessage fallback is ever needed.
 */

import type {
  AddSegmentRequest,
  GenerateReportRequest,
  SwitchSegmentRequest,
} from "./types.ts";

/** `switch_segment` request. `client_ts` is the client's switch instant (ms). */
export function buildSwitchRequest(
  kind: string,
  now: number = Date.now(),
): SwitchSegmentRequest {
  return { kind, client_ts: now };
}

/** `generate_report` request over [startTs, endTs] (both epoch ms). */
export function buildReportRequest(
  kind: string,
  startTs: number,
  endTs: number,
): GenerateReportRequest {
  return { kind, start_ts: startTs, end_ts: endTs };
}

/** `add_segment` request: paint [startTs, endTs] as `kind` (both epoch ms). */
export function buildAddSegmentRequest(
  kind: string,
  startTs: number,
  endTs: number,
): AddSegmentRequest {
  return { kind, start_ts: startTs, end_ts: endTs };
}

/** Best-effort human-readable message from an unknown thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  if (typeof err === "string" && err !== "") {
    return err;
  }
  if (err && typeof err === "object") {
    const rec = err as Record<string, unknown>;
    // pydoover RPC errors surface as {code, message} nested in status.message.
    const message = rec.message;
    if (typeof message === "string" && message !== "") {
      return message;
    }
    if (message && typeof message === "object") {
      const inner = (message as Record<string, unknown>).message;
      if (typeof inner === "string" && inner !== "") {
        return inner;
      }
    }
  }
  return "Something went wrong";
}
