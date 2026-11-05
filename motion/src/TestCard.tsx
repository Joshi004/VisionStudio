import { AbsoluteFill, useCurrentFrame } from "remotion";

import { DISPLAY_FONT, TEXT_FONT } from "./fonts";
import type { GraphicInput } from "./types";

// The test card of GFX-005: it proves the size, the frame rate and the exact frame count, the two
// fonts, the colours, and where the safe area and the caption area are. Every pixel depends only
// on the frame number, so two renders of the same input are identical.
export function TestCard({ width, height, fps, frames, resolved }: GraphicInput) {
  const frame = useCurrentFrame();
  const { theme, safe_area: safe, caption_zone: caption } = resolved;
  const portrait = height > width;
  const titleSize = height * (portrait ? 0.036 : 0.06);
  const textSize = height * (portrait ? 0.024 : 0.032);
  const line = Math.max(2, Math.round(height / 540));
  const progress = frames > 1 ? frame / (frames - 1) : 1;

  const barLeft = safe.left;
  const barWidth = safe.right - safe.left;
  const barHeight = Math.round(height * 0.03);
  const barTop = Math.round(caption.top - height * 0.12);

  return (
    <AbsoluteFill style={{ background: theme.background, color: theme.text }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          width,
          top: caption.top,
          height: caption.bottom - caption.top,
          background: theme.surface,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: safe.left,
          top: safe.top,
          width: safe.right - safe.left,
          height: safe.bottom - safe.top,
          boxSizing: "border-box",
          border: `${line}px dashed ${theme.muted}`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: safe.left + titleSize * 0.5,
          top: safe.top + titleSize * 0.4,
          fontFamily: DISPLAY_FONT,
          fontSize: titleSize,
          lineHeight: 1.1,
        }}
      >
        Test card
      </div>
      <div
        style={{
          position: "absolute",
          left: safe.left + titleSize * 0.5,
          top: safe.top + titleSize * 1.9,
          fontFamily: TEXT_FONT,
          fontSize: textSize,
          color: theme.muted,
        }}
      >
        {`${width} x ${height}, ${fps} fps, ${frames} frames`}
      </div>
      <div
        style={{
          position: "absolute",
          left: safe.left + titleSize * 0.5,
          top: safe.top + titleSize * 3.2,
          fontFamily: DISPLAY_FONT,
          fontSize: titleSize * 1.6,
          color: theme.number,
        }}
      >
        {`${frame + 1} / ${frames}`}
      </div>
      <div
        style={{
          position: "absolute",
          left: barLeft,
          top: barTop,
          width: barWidth,
          height: barHeight,
          background: theme.surface,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: barLeft,
          top: barTop,
          width: Math.round(barWidth * progress),
          height: barHeight,
          background: theme.accent,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: safe.left + titleSize * 0.5,
          top: caption.top - textSize * 1.6,
          fontFamily: TEXT_FONT,
          fontSize: textSize * 0.8,
          color: theme.muted,
        }}
      >
        caption area below
      </div>
    </AbsoluteFill>
  );
}
