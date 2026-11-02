import { AbsoluteFill } from "remotion";

import { DISPLAY_FONT, TEXT_FONT } from "./fonts";
import type { GraphicInput } from "./types";

// The composition of an engine whose phase is not built yet (Templates, Blocks, Generated).
export function NotBuiltYet({ engine, height, resolved }: GraphicInput) {
  const theme = resolved.theme;
  return (
    <AbsoluteFill
      style={{
        background: theme.background,
        color: theme.text,
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
      }}
    >
      <div style={{ fontFamily: DISPLAY_FONT, fontSize: height * 0.05 }}>Not built yet</div>
      <div style={{ fontFamily: TEXT_FONT, fontSize: height * 0.028, color: theme.muted }}>
        {engine}
      </div>
    </AbsoluteFill>
  );
}
