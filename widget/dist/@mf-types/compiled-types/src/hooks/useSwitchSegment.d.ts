/**
 * Encapsulates the segment-switch flow.
 *
 * WIRE-SHAPE DECISION (see widget/README.md): doover-js `useSendRpc` posts
 * exactly the pydoover RPCManager request wire shape the processor expects, so
 * we use it directly rather than the manual useSendMessage fallback. It calls
 * `RpcDispatcher.send` which does
 *   postMessage(dv-rpc, { data: { type:"rpc", method, request, app_key } })
 * and pydoover's `_handle_request` reads only type/method/app_key/request
 * (it ignores the absent status/response the manual path would add).
 *
 * Pending model: after firing, the dropdown is disabled until the tag_values
 * aggregate reflects the new kind, the RPC errors, or a ~15s safety timeout.
 */
export interface SwitchSegmentResult {
    /** Fire a switch to `kind`. No-op client-side if it equals the current kind. */
    switchTo: (kind: string) => void;
    /** The kind we're waiting to see reflected, or null when idle. */
    pendingKind: string | null;
    /** True while a switch is in flight. */
    isPending: boolean;
    /** Last error message (RPC-level), or null. */
    error: string | null;
    /** Dismiss the current error. */
    clearError: () => void;
}
export declare function useSwitchSegment(agentId: string | undefined, appKey: string, currentKind: string | null): SwitchSegmentResult;
