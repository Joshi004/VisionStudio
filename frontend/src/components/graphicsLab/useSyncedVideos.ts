import { useCallback, useEffect, useRef, useState } from "react";

type UseSyncedVideosInput = {
  fps: number;
  /** The length of the graphic, in frames (from the resolved brief). */
  frames: number;
  /** The videos on the page, in the order of the cards. The first one is the leader. */
  keys: readonly string[];
};

export type SyncedVideos = {
  /** A ref callback for the video of one card. The same function every time for one key. */
  register: (key: string) => (element: HTMLVideoElement | null) => void;
  /** Call when a video has loaded (or has a new source), so it joins the others' position. */
  onLoaded: (key: string) => void;
  playing: boolean;
  /** The frame every video shows, counted from 0. */
  frame: number;
  play: () => void;
  pause: () => void;
  /** Pauses every video and shows this frame (clamped to the graphic's length) in all of them. */
  seekFrame: (frame: number) => void;
  /** Pauses and moves every video by this many frames. */
  step: (delta: number) => void;
};

/**
 * One control for several videos (GFX-011). The first video is the **leader**: it is the only
 * one with sound (every video carries the same voice, so four at once would echo), and while
 * playing, any other video that is more than one frame away from it is moved to its time. A seek
 * or a step pauses all of them and sets the same time on each, in the middle of the frame, so
 * every browser shows exactly that frame.
 */
export function useSyncedVideos({ fps, frames, keys }: UseSyncedVideosInput): SyncedVideos {
  const elements = useRef(new Map<string, HTMLVideoElement>());
  const callbacks = useRef(new Map<string, (element: HTMLVideoElement | null) => void>());
  const [playing, setPlaying] = useState(false);
  const [frame, setFrame] = useState(0);

  const leaderKey = keys[0] ?? null;
  // The latest values, for the callbacks and the loop that must not be made again on every change.
  const latest = useRef({ playing, frame, leaderKey });
  useEffect(() => {
    latest.current = { playing, frame, leaderKey };
  });

  const timeOf = useCallback((at: number) => (at + 0.5) / fps, [fps]);
  const frameAt = useCallback(
    (seconds: number) => Math.min(Math.max(Math.floor(seconds * fps), 0), frames - 1),
    [fps, frames],
  );

  const applySound = useCallback(() => {
    for (const [key, element] of elements.current) {
      element.muted = key !== latest.current.leaderKey;
    }
  }, []);

  // Only the leader makes sound. This runs again when the leader changes.
  useEffect(applySound, [applySound, leaderKey]);

  const register = useCallback(
    (key: string) => {
      let callback = callbacks.current.get(key);
      if (callback === undefined) {
        callback = (element: HTMLVideoElement | null) => {
          if (element === null) {
            elements.current.delete(key);
          } else {
            element.muted = key !== latest.current.leaderKey;
            elements.current.set(key, element);
          }
        };
        callbacks.current.set(key, callback);
      }
      return callback;
    },
    [],
  );

  const pauseAll = useCallback(() => {
    for (const element of elements.current.values()) {
      element.pause();
    }
    setPlaying(false);
  }, []);

  const seekFrame = useCallback(
    (target: number) => {
      const clamped = Math.min(Math.max(Math.round(target), 0), frames - 1);
      pauseAll();
      for (const element of elements.current.values()) {
        element.currentTime = timeOf(clamped);
      }
      setFrame(clamped);
    },
    [frames, pauseAll, timeOf],
  );

  const play = useCallback(() => {
    if (elements.current.size === 0) {
      return;
    }
    // Pressing play at the end starts again from the beginning.
    const from = latest.current.frame >= frames - 1 ? 0 : latest.current.frame;
    for (const element of elements.current.values()) {
      element.currentTime = timeOf(from);
      // A refusal (the browser's autoplay rules) leaves the video paused; the loop below then
      // sees the leader paused and stops.
      void element.play().catch(() => undefined);
    }
    setFrame(from);
    setPlaying(true);
  }, [frames, timeOf]);

  const pause = useCallback(() => {
    const leader =
      latest.current.leaderKey !== null ? elements.current.get(latest.current.leaderKey) : undefined;
    const target = leader !== undefined ? frameAt(leader.currentTime) : latest.current.frame;
    seekFrame(target);
  }, [frameAt, seekFrame]);

  const step = useCallback(
    (delta: number) => seekFrame(latest.current.frame + delta),
    [seekFrame],
  );

  const onLoaded = useCallback(
    (key: string) => {
      const element = elements.current.get(key);
      if (element === undefined) {
        return;
      }
      element.currentTime = timeOf(latest.current.frame);
      if (latest.current.playing) {
        void element.play().catch(() => undefined);
      }
    },
    [timeOf],
  );

  // While playing: read the leader's time every display frame, keep the others with it, and stop
  // at the end. With no video left, there is nothing to play.
  useEffect(() => {
    if (!playing) {
      return;
    }
    let handle = 0;
    const tick = () => {
      const leader = leaderKey !== null ? elements.current.get(leaderKey) : undefined;
      if (leader === undefined) {
        setPlaying(false);
        return;
      }
      const seconds = leader.currentTime;
      setFrame(frameAt(seconds));
      for (const [key, element] of elements.current) {
        if (key !== leaderKey && Math.abs(element.currentTime - seconds) > 1 / fps) {
          element.currentTime = seconds;
        }
      }
      if (leader.ended) {
        seekFrame(frames - 1);
        return;
      }
      if (leader.paused) {
        // The browser refused to play it: show the frame it is on, paused.
        seekFrame(frameAt(seconds));
        return;
      }
      handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, [playing, leaderKey, fps, frames, frameAt, seekFrame]);

  // With no leader (no card has a video) nothing is playing, whatever the state says.
  return {
    register,
    onLoaded,
    playing: playing && leaderKey !== null,
    frame,
    play,
    pause,
    seekFrame,
    step,
  };
}
