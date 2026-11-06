// A hand-written sample of a callout component (CMO-001). It follows the rules the model will get
// in CMO-003 (§4.4.1 of Callouts_motion_implementation_phases.md): a transparent canvas, only the
// given words, time from the props, a layout worked out from `width` and `height`.
//
// It is used only to check the motion service by hand (a render, a check, an overlay on a shot):
// the app never reads it, and it is not bundled into the service.
import { interpolate, spring, useCurrentFrame } from "remotion";

type Props = {
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  frameHeight: number;
  kind: string;
  placement: string;
  parts: { id: string; text: string; role: string; colour: string; frame: number }[];
  theme: {
    surface: string;
    text: string;
    muted: string;
    accent: string;
    fontDisplay: string;
    fontText: string;
  };
  look: Record<string, string>;
  exitFrame: number;
};

export default function CalloutCard({ width, height, fps, frameHeight, parts, theme }: Props) {
  const frame = useCurrentFrame();
  const margin = Math.round(height * 0.08);
  const fontSize = Math.round(frameHeight * 0.045);
  const radius = Math.round(height * 0.08);

  return (
    <div
      style={{
        position: "absolute",
        left: margin,
        top: margin,
        width: width - margin * 2,
        height: height - margin * 2,
        boxSizing: "border-box",
        padding: margin,
        borderRadius: radius,
        background: theme.surface,
        // A soft shadow: the edge the fringe test looks at.
        boxShadow: `0 ${Math.round(margin / 2)}px ${margin}px rgba(0, 0, 0, 0.55)`,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        gap: margin / 2,
        overflow: "hidden",
      }}
    >
      {parts.map((part) => {
        const start = part.frame;
        const enter = spring({ frame: frame - start, fps, config: { damping: 200 }, durationInFrames: Math.round(fps * 0.4) });
        const opacity = interpolate(frame, [start, start + Math.round(fps * 0.3)], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={part.id}
            style={{
              color: part.colour,
              fontFamily: theme.fontDisplay,
              fontSize,
              lineHeight: 1.15,
              opacity,
              transform: `translateY(${(1 - enter) * fontSize * 0.5}px)`,
            }}
          >
            {part.text}
          </div>
        );
      })}
    </div>
  );
}
