/**
 * Retroactive "add segment" flow: fires the `add_segment` RPC on dv-rpc (the
 * processor paints the interval + merges overlaps, the single authoritative
 * writer). On success it calls `onApplied` so the caller can refetch the
 * segment history — a retroactive add deletes/recreates segment messages, which
 * the live create-only subscription can't reconcile on its own.
 */

import { useCallback, useState } from "react";
import { useSendRpc } from "doover-js/react";

import { buildAddSegmentRequest, errorMessage } from "../lib/rpc.ts";
import { RPC_CHANNEL, type AddSegmentRequest } from "../lib/types.ts";

export interface AddSegmentResult {
  /** Paint [startTs, endTs] as `kind`. Resolves true on success. */
  add: (kind: string, startTs: number, endTs: number) => Promise<boolean>;
  pending: boolean;
  error: string | null;
  clearError: () => void;
}

export function useAddSegment(
  agentId: string | undefined,
  appKey: string,
  onApplied: () => void,
): AddSegmentResult {
  const rpc = useSendRpc<AddSegmentRequest, { changed?: boolean }>(
    { agentId, channelName: RPC_CHANNEL },
    { method: "add_segment", app_key: appKey },
  );

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = useCallback(
    async (kind: string, startTs: number, endTs: number): Promise<boolean> => {
      if (!agentId) {
        setError("No agent context — cannot add segment.");
        return false;
      }
      setError(null);
      setPending(true);
      const commandId = `add-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      try {
        await rpc.mutateAsync({
          commandId,
          request: buildAddSegmentRequest(kind, startTs, endTs),
        });
        onApplied();
        return true;
      } catch (err: unknown) {
        setError(errorMessage(err));
        return false;
      } finally {
        setPending(false);
      }
    },
    [agentId, rpc, onApplied],
  );

  return { add, pending, error, clearError: () => setError(null) };
}
