// Bundles the compositions once, at image build time, so nothing is written to the read-only
// root filesystem when the container runs. Also makes sure the browser is downloaded (the
// container has no internet when it runs) and records the versions /health reports.
import { readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { bundle } from "@remotion/bundler";
import { ensureBrowser } from "@remotion/renderer";

const root = resolve(import.meta.dirname, "..");
const outDir = resolve(root, "build/bundle");

await bundle({ entryPoint: resolve(root, "src/index.ts"), outDir });

const status = await ensureBrowser();
if (status.type !== "local-puppeteer-browser" && status.type !== "user-defined-path") {
  throw new Error(`No browser is available (${status.type}).`);
}
const chrome = execFileSync(status.path, ["--version"], { encoding: "utf8" }).trim();
const remotion = (
  JSON.parse(readFileSync(resolve(root, "node_modules/remotion/package.json"), "utf8")) as {
    version: string;
  }
).version;

writeFileSync(
  resolve(root, "build/versions.json"),
  JSON.stringify({ remotion, chrome, browser_path: status.path }, null, 2),
);
console.log(`bundled; remotion ${remotion}; ${chrome}`);
