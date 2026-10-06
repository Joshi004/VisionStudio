import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import type { Scene } from "../../api/scenes";

type PlayableScene = Pick<Scene, "id" | "start_s" | "end_s">;

export interface ScenePlayer {
  /** Attach to one `<audio>` element that plays the voiceover. */
  audioRef: RefObject<HTMLAudioElement | null>;
  /** The scene that is playing now, or null. */
  playingId: number | null;
  play: (scene: PlayableScene) => void;
  stop: () => void;
  /** Event handlers for the `<audio>` element: stop at the end of the scene, however it got there. */
  onTimeUpdate: () => void;
  onPause: () => void;
  onEnded: () => void;
}

/**
 * Plays one scene's slice of the voiceover: from its start to its end, then stops.
 *
 * It watches the playback position with `requestAnimationFrame` while a scene is playing
 * (about every 16 ms, so it stops within a frame of the end). This is a local check of an
 * audio element, not polling of the backend, and it runs only while something plays. The
 * element's own `timeupdate` event is a backup for a tab in the background, where animation
 * frames pause.
 */
export function useScenePlayer(): ScenePlayer {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const frameRef = useRef<number | null>(null);
  // The scene being played. Compared by identity, so a scene that was replaced by another
  // click (or stopped) ends its own watcher.
  const sceneRef = useRef<PlayableScene | null>(null);
  const [playingId, setPlayingId] = useState<number | null>(null);

  const cancelFrame = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    cancelFrame();
    sceneRef.current = null;
    audioRef.current?.pause();
    setPlayingId(null);
  }, [cancelFrame]);

  const play = useCallback(
    (scene: PlayableScene) => {
      const audio = audioRef.current;
      if (!audio) {
        return;
      }
      cancelFrame();
      sceneRef.current = scene;
      audio.currentTime = scene.start_s;
      setPlayingId(scene.id);

      const watch = () => {
        if (sceneRef.current !== scene) {
          return;
        }
        if (audio.currentTime >= scene.end_s) {
          stop();
          return;
        }
        frameRef.current = requestAnimationFrame(watch);
      };
      audio.play().then(
        () => {
          if (sceneRef.current === scene) {
            frameRef.current = requestAnimationFrame(watch);
          }
        },
        () => {
          // The browser refused to play, or the file could not be loaded.
          if (sceneRef.current === scene) {
            stop();
          }
        },
      );
    },
    [cancelFrame, stop],
  );

  // Leaving the page stops the frame watcher. The sound stops by itself when the browser
  // removes the `<audio>` element from the page.
  useEffect(() => cancelFrame, [cancelFrame]);

  const onTimeUpdate = useCallback(() => {
    const audio = audioRef.current;
    const scene = sceneRef.current;
    if (audio && scene && audio.currentTime >= scene.end_s) {
      stop();
    }
  }, [stop]);

  // Paused or ended by something other than this player (the media keys, for example).
  const onPause = useCallback(() => {
    if (sceneRef.current !== null) {
      stop();
    }
  }, [stop]);

  return { audioRef, playingId, play, stop, onTimeUpdate, onPause, onEnded: onPause };
}
