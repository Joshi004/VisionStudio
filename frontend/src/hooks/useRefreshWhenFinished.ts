import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { invalidateAfterJobAction } from "../api/jobs";

/**
 * Loads everything once when `active` changes from true to false, that is, when the last
 * job on screen has just finished. A finished job can change other parts of the page: a new
 * transcript makes the scenes out of date, a new clip changes whether Render is allowed.
 */
export function useRefreshWhenFinished(active: boolean) {
  const queryClient = useQueryClient();
  const wasActive = useRef(active);

  useEffect(() => {
    if (wasActive.current && !active) {
      void invalidateAfterJobAction(queryClient);
    }
    wasActive.current = active;
  }, [active, queryClient]);
}
