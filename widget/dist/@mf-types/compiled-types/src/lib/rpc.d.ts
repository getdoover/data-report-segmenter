/**
 * dv-rpc request-payload builders + error-message extraction.
 *
 * These build the `request` object of the pydoover RPCManager wire shape.
 * doover-js `useSendRpc` wraps this as `{type:"rpc", method, request, app_key}`
 * (see rsbuild widget README "wire-shape decision") — we only own the inner
 * `request` here so the same builders are reused verbatim if the manual
 * useSendMessage fallback is ever needed.
 */
import type { GenerateReportRequest, SwitchSegmentRequest } from "./types.ts";
/** `switch_segment` request. `client_ts` is the client's switch instant (ms). */
export declare function buildSwitchRequest(kind: string, now?: number): SwitchSegmentRequest;
/** `generate_report` request over [startTs, endTs] (both epoch ms). */
export declare function buildReportRequest(kind: string, startTs: number, endTs: number): GenerateReportRequest;
/** Best-effort human-readable message from an unknown thrown value. */
export declare function errorMessage(err: unknown): string;
