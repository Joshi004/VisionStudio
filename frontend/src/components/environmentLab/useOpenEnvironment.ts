import { useCallback } from "react";
import { useSearchParams } from "react-router";

const PARAM = "environment";

/**
 * The id in `?environment=`: a positive whole number, or null when the address has none or has
 * something else. A stray value must never reach the server as an id.
 */
export function environmentIdFrom(value: string | null): number | null {
  if (value === null || !/^[1-9][0-9]{0,15}$/.test(value)) {
    return null;
  }
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

/**
 * The open environment is kept in the address (`/lab/environments?environment=12`), so its page
 * can be linked to. Opening one adds a history entry, so the browser's back button returns to
 * the library. `open(null)` goes back to the library.
 */
export function useOpenEnvironment(): readonly [number | null, (id: number | null) => void] {
  const [params, setParams] = useSearchParams();
  const openId = environmentIdFrom(params.get(PARAM));

  const open = useCallback(
    (id: number | null) => {
      setParams((current) => {
        const next = new URLSearchParams(current);
        if (id === null) {
          next.delete(PARAM);
        } else {
          next.set(PARAM, String(id));
        }
        return next;
      });
    },
    [setParams],
  );

  return [openId, open] as const;
}
