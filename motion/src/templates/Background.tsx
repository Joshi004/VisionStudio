import { AbsoluteFill } from "remotion";
import type { CSSProperties } from "react";

import { withAlpha } from "./layout";
import type { Theme } from "../types";

// The four backgrounds of the theme (§4.5.1). They are drawn over the whole frame, the caption
// area included, and they do not move.
export function Background({ theme, width, height }: { theme: Theme; width: number; height: number }) {
  const style: CSSProperties = { background: theme.background };
  if (theme.background_style === "gradient") {
    style.background = `linear-gradient(to bottom, ${theme.background}, ${theme.surface})`;
  } else if (theme.background_style === "grid") {
    // A faint grid of `surface` lines every 8 percent of the height, from the top left corner.
    const step = Math.round(0.08 * height);
    const line = Math.max(1, Math.round(height / 540));
    const rule = (direction: string) =>
      `linear-gradient(${direction}, ${theme.surface} ${line}px, transparent ${line}px)`;
    style.backgroundColor = theme.background;
    style.backgroundImage = `${rule("to bottom")}, ${rule("to right")}`;
    style.backgroundSize = `${step}px ${step}px`;
  } else if (theme.background_style === "glow") {
    // A soft glow of `accent` at 8 percent opacity in the centre, fading out linearly.
    const radius = Math.round(0.6 * Math.max(width, height));
    style.backgroundColor = theme.background;
    style.backgroundImage = `radial-gradient(circle ${radius}px at 50% 50%, ${withAlpha(theme.accent, 0.08)}, ${withAlpha(theme.accent, 0)})`;
  }
  return <AbsoluteFill style={style} />;
}
