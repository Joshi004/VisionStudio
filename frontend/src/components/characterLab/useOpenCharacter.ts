import { useCallback } from "react";
import { useSearchParams } from "react-router";

const PARAM = "character";

/**
 * The id in `?character=`: a positive whole number, or null when the address has none or has
 * something else. A stray value must never reach the server as an id.
 */
export function characterIdFrom(value: string | null): number | null {
  if (value === null || !/^[1-9][0-9]{0,15}$/.test(value)) {
    return null;
  }
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

/**
 * The open character is kept in the address (`/lab/characters?character=12`), so a character
 * page can be linked to. Opening one adds a history entry, so the browser's back button returns
 * to the library. `open(null)` goes back to the library.
 */
export function useOpenCharacter(): readonly [number | null, (id: number | null) => void] {
  const [params, setParams] = useSearchParams();
  const openId = characterIdFrom(params.get(PARAM));

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
