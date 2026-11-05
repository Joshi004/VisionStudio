import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { runIdFrom } from "./useOpenGraphicsRun";

const PARAM = "trial";

/**
 * The trial set in `?trial=`: a positive whole number, or null when the address has none or has
 * something else. It has the same shape as a run id, so the run's check is used.
 */
export function trialSetFrom(value: string | null): number | null {
  return runIdFrom(value);
}

/**
 * The open trial set is kept in the address (`/lab/graphics?trial=3`), so a summary can be linked
 * to. A run opened from the summary adds `run=` beside it, and closing the run returns to the
 * summary. `open(null)` goes back to the list.
 */
export function useOpenGraphicsTrial(): readonly [number | null, (setNo: number | null) => void] {
  const [params, setParams] = useSearchParams();
  const openSet = trialSetFrom(params.get(PARAM));

  const open = useCallback(
    (setNo: number | null) => {
      setParams((current) => {
        const next = new URLSearchParams(current);
        if (setNo === null) {
          next.delete(PARAM);
        } else {
          next.set(PARAM, String(setNo));
        }
        return next;
      });
    },
    [setParams],
  );

  return [openSet, open] as const;
}
