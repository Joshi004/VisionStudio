import { AbsoluteFill, useCurrentFrame } from "remotion";
import { useMemo } from "react";

import type { GraphicInput } from "../types";
import { readSoundbite } from "./props";

// The overlay of a sound bite clip (SB-009, `Sound_bite_implementation_phases.md` §4.7): the lower
// third that names the speaker, the role at the time, the venue and the month of the recording, and
// a small credit for the source video. The canvas is transparent and as large as the frame, and the
// backend lays it over the picture of the clip, so this file only draws what `soundbite_render.py`
// placed. Every pixel depends only on the frame number.

const PLATE = "rgba(11, 15, 23, 0.92)";
const NAME_COLOUR = "#FFFFFF";
const DETAIL_COLOUR = "#C9D1DC";
const CREDIT_PLATE = "rgba(11, 15, 23, 0.6)";

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

export function SoundbiteOverlay(props: GraphicInput) {
  const resolved = useMemo(() => readSoundbite(props), [props]);
  const frame = useCurrentFrame();
  const { lower_third: third, credit, accent, fonts } = resolved;

  // Fades in over `fade_frames` from its first frame and out over the same number before its last.
  const thirdOpacity =
    third === null
      ? 0
      : third.fade_frames === 0
        ? frame >= third.start_frame && frame < third.end_frame
          ? 1
          : 0
        : Math.min(
            clamp((frame - third.start_frame) / third.fade_frames, 0, 1),
            clamp((third.end_frame - 1 - frame) / third.fade_frames, 0, 1),
          );

  return (
    <AbsoluteFill style={{ background: "transparent", overflow: "hidden" }}>
      {third !== null && thirdOpacity > 0 && (
        <div
          style={{
            position: "absolute",
            left: third.box[0],
            top: third.box[1],
            width: third.box[2],
            height: third.box[3],
            boxSizing: "border-box",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            gap: third.box[3] * 0.06,
            padding: `0 ${third.box[3] * 0.25}px`,
            background: PLATE,
            borderLeft: `${Math.max(4, Math.round(third.box[3] * 0.06))}px solid ${accent}`,
            borderRadius: third.box[3] * 0.12,
            opacity: thirdOpacity,
          }}
        >
          <span
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              fontFamily: fonts.display,
              fontSize: third.box[3] * 0.38,
              color: NAME_COLOUR,
            }}
          >
            {third.name}
          </span>
          {third.detail !== "" && (
            <span
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                fontFamily: fonts.text,
                fontSize: third.box[3] * 0.26,
                color: DETAIL_COLOUR,
              }}
            >
              {third.detail}
            </span>
          )}
        </div>
      )}
      {credit !== null && (
        <div
          style={{
            position: "absolute",
            left: credit.box[0],
            top: credit.box[1],
            width: credit.box[2],
            height: credit.box[3],
            boxSizing: "border-box",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
          }}
        >
          <span
            style={{
              maxWidth: "100%",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              padding: `${credit.box[3] * 0.12}px ${credit.box[3] * 0.4}px`,
              background: CREDIT_PLATE,
              borderRadius: credit.box[3] * 0.3,
              fontFamily: fonts.text,
              fontSize: credit.box[3] * 0.5,
              color: DETAIL_COLOUR,
            }}
          >
            {credit.text}
          </span>
        </div>
      )}
    </AbsoluteFill>
  );
}
