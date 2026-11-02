import { continueRender, delayRender, staticFile } from "remotion";
import { loadFont } from "@remotion/fonts";

// The two fonts of the lab (G-11), loaded from the files in public/fonts and never from the
// internet. The family names are the ones the resolved brief gives (`graphics_lab.FONTS`).
export const DISPLAY_FONT = "Montserrat ExtraBold";
export const TEXT_FONT = "Inter Medium";

const handle = delayRender("Loading the fonts", { timeoutInMilliseconds: 30_000 });

Promise.all([
  loadFont({ family: DISPLAY_FONT, url: staticFile("fonts/Montserrat-ExtraBold.ttf") }),
  loadFont({ family: TEXT_FONT, url: staticFile("fonts/Inter-Medium.ttf") }),
])
  .then(() => continueRender(handle))
  .catch((error: unknown) => {
    // A missing font must fail the render, never fall back to another font silently.
    throw new Error(`The fonts could not be loaded: ${String(error)}`);
  });
