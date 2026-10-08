import { useEffect, useState } from "react";

/**
 * The current time in milliseconds since 1970, updated once a second while `ticking` is
 * true, so a "running 1 min 20 s" text counts up. It makes no request to the backend.
 *
 * `loadedAt` is when the data on screen was loaded. The result is never earlier than that,
 * so a job that has just appeared does not show a negative time before the first tick.
 */
export function useNow(ticking: boolean, loadedAt: number): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!ticking) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [ticking]);

  return Math.max(now, loadedAt);
}
