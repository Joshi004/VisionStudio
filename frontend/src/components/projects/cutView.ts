import type { Scene } from "../../api/scenes";

/** The part of a scene these helpers read: where it begins and ends in the script's words. */
type SceneWords = Pick<Scene, "first_word" | "last_word">;

/**
 * The cuts, by the number of the word they follow. A cut is the end of a scene, so it maps
 * to the scene it ends. The last scene ends with the script, which is not a cut.
 */
export function cutsByWord<T extends SceneWords>(scenes: T[]): Map<number, T> {
  const cuts = new Map<number, T>();
  for (const scene of scenes.slice(0, -1)) {
    if (scene.last_word !== null) {
      cuts.set(scene.last_word, scene);
    }
  }
  return cuts;
}

/** Each scene by the number of its first word. */
export function scenesByFirstWord<T extends SceneWords>(scenes: T[]): Map<number, T> {
  const starts = new Map<number, T>();
  for (const scene of scenes) {
    if (scene.first_word !== null) {
      starts.set(scene.first_word, scene);
    }
  }
  return starts;
}

/** For every word, the position (from 0) of the scene it belongs to. */
export function sceneOfEachWord(scenes: SceneWords[], wordCount: number): number[] {
  const positions: number[] = new Array<number>(wordCount).fill(0);
  scenes.forEach((scene, position) => {
    if (scene.first_word === null || scene.last_word === null) {
      return;
    }
    for (let word = scene.first_word; word <= scene.last_word && word < wordCount; word += 1) {
      positions[word] = position;
    }
  });
  return positions;
}

/**
 * The gaps a cut may move to, as the numbers of the word each follows (both ends included).
 * A cut moves only within the two scenes beside it, so each keeps at least one word.
 * Null when there is no cut after that word.
 */
export function moveRange(
  scenes: SceneWords[],
  cutWord: number,
): { from: number; to: number } | null {
  const position = scenes.findIndex((scene) => scene.last_word === cutWord);
  const before = scenes[position];
  const after = scenes[position + 1];
  if (position < 0 || !after || before.first_word === null || after.last_word === null) {
    return null;
  }
  return { from: before.first_word, to: after.last_word - 1 };
}
