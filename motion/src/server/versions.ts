import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");

export type Versions = { remotion: string; chrome: string | null };

// The versions /health reports. The image build (scripts/bundle.ts) records Chrome's version in
// build/versions.json. Without that file (a local run) Chrome's version is unknown.
export function readVersions(): Versions {
  const file = resolve(root, "build/versions.json");
  if (existsSync(file)) {
    const recorded = JSON.parse(readFileSync(file, "utf8")) as Partial<Versions>;
    if (typeof recorded.remotion === "string") {
      return {
        remotion: recorded.remotion,
        chrome: typeof recorded.chrome === "string" ? recorded.chrome : null,
      };
    }
  }
  const remotion = JSON.parse(
    readFileSync(resolve(root, "node_modules/remotion/package.json"), "utf8"),
  ) as { version: string };
  return { remotion: remotion.version, chrome: null };
}
