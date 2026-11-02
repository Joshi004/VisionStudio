/**
 * The shot lists of a project (definitions, references, requests, prompts, takes) can be asked
 * for the shots of one scene only, or for no shots at all. Every scene is still listed with a
 * `summary` that counts all of its shots, so a scene that is closed on the page can show where
 * it stands without its shots being loaded. The page keeps one scene open at a time.
 */

/** The id of the one scene whose shots are loaded, or null when every scene is closed. */
export type OpenScene = string | null;

/** The query string of a shot list for the open scene. */
export function sceneQuery(sceneId: OpenScene) {
  return sceneId === null
    ? { shots: false }
    : { scene_id: sceneId };
}

/** True when a scene sent a summary that counts shots but not the shots themselves (yet). */
export function shotsNotLoaded(scene: {
  shots: readonly unknown[];
  summary: { total: number };
}): boolean {
  return scene.shots.length === 0 && scene.summary.total > 0;
}

/** True when any scene of a list has a shot whose job is waiting or running. */
export function anySceneActive(
  entries: readonly { summary: { active: number } }[] | undefined,
): boolean {
  return entries?.some((scene) => scene.summary.active > 0) ?? false;
}
