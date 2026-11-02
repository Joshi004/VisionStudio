// Copies the two fonts of the lab (G-11) from the backend's font folder into public/fonts, for
// working on the compositions outside Docker. The image gets the same files through a Compose
// build context (see motion/Dockerfile), so there is never a second copy in git.
import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const source = resolve(import.meta.dirname, "../../backend/app/assets/fonts");
const target = resolve(import.meta.dirname, "../public/fonts");
mkdirSync(target, { recursive: true });
for (const file of ["Montserrat-ExtraBold.ttf", "Inter-Medium.ttf"]) {
  copyFileSync(resolve(source, file), resolve(target, file));
  console.log(`copied ${file}`);
}
