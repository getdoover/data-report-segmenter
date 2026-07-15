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

import { useCallback, useEffect, useRef, useState } from "react";
import { useSendRpc } from "doover-js/react";

import { buildSwitchRequest, errorMessage } from "../lib/rpc.ts";
import { RPC_CHANNEL, type SwitchSegmentRequest } from "../lib/types.ts";

const SAFETY_TIMEOUT_MS = 15000;

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

export function useSwitchSegment(
  agentId: string | undefined,
  appKey: string,
  currentKind: string | null,
): SwitchSegmentResult {
  const rpc = useSendRpc<SwitchSegmentRequest, { current_segment?: unknown }>(
    { agentId, channelName: RPC_CHANNEL },
    { method: "switch_segment", app_key: appKey },
  );

  const [pendingKind, setPendingKind] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPending = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setPendingKind(null);
  }, []);

  // Resolve the pending state once tag_values reflects the requested kind.
  useEffect(() => {
    if (pendingKind !== null && currentKind === pendingKind) {
      clearPending();
    }
  }, [currentKind, pendingKind, clearPending]);

  // Belt-and-suspenders: never leave the dropdown disabled forever.
  useEffect(() => () => clearPending(), [clearPending]);

  const switchTo = useCallback(
    (kind: string) => {
      // Picking the current kind is a no-op client-side.
      if (kind === currentKind || kind === "") {
        return;
      }
      if (!agentId) {
        setError("No agent context — cannot switch segment.");
        return;
      }
      setError(null);
      setPendingKind(kind);
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        setPendingKind(null);
      }, SAFETY_TIMEOUT_MS);

      const commandId = `switch-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      rpc
        .mutateAsync({ commandId, request: buildSwitchRequest(kind) })
        .catch((err: unknown) => {
          setError(errorMessage(err));
          clearPending();
        });
    },
    [agentId, currentKind, rpc, clearPending],
  );

  return {
    switchTo,
    pendingKind,
    isPending: pendingKind !== null,
    error,
    clearError: () => setError(null),
  };
}
