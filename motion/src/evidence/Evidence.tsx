import { useEffect, useMemo, useState } from "react";
import { AbsoluteFill, Img, useCurrentFrame } from "remotion";

import type { GraphicInput } from "../types";
import { readEvidence } from "./props";
import type { Box, EvidenceImage } from "./props";

// The evidence clip of EVD-008 (`Evidence_layer_implementation_phases.md` §4.7). It opens on the
// screenshot, zooms in to the quote, sweeps a highlight across the quote's lines in the accent
// colour, and holds. A badge names the source. The camera, the timeline and every box come from
// the backend (`evidence_clip_layout.py`), so this file only draws them.
//
// The pictures are placed at their size on the output frame (`left`, `top`, `width`, `height`),
// never scaled by a CSS transform, so that the browser draws them from their full resolution and
// the quote's text stays sharp. Every pixel depends only on the frame number.

const BADGE_BACKGROUND = "rgba(11, 15, 23, 0.95)";
const BADGE_TEXT = "#FFFFFF";
const BADGE_MUTED = "#C9D1DC";
const BADGE_FADE_FRAMES = 8;
// How much of the line's height the highlight reaches above and below the text, in output pixels.
const HIGHLIGHT_PAD_PX = 2;
// The line between the evidence panel and the callout panel of a split shot.
const PANEL_LINE_PX = 4;

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function blobUrl(image: EvidenceImage): string {
  const binary = atob(image.base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return URL.createObjectURL(new Blob([bytes], { type: image.mime }));
}

// An address for a picture of the request, made once and let go of when the composition goes. A
// blob address avoids any limit a browser puts on the length of a `data:` address.
function useBlobUrl(image: EvidenceImage | null): string | null {
  const [url] = useState(() => (image === null ? null : blobUrl(image)));
  useEffect(
    () => () => {
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );
  return url;
}

type Camera = { x: number; y: number; width: number };

// The camera's place at a frame: its middle moves in a straight line, its width by the same ratio
// every frame (so the zoom looks even), both eased.
function cameraAt(frame: number, start: Box, end: Box, zoomStart: number, zoomEnd: number): Camera {
  const t = easeInOut(clamp((frame - zoomStart) / (zoomEnd - zoomStart), 0, 1));
  const centreX = start[0] + start[2] / 2 + (end[0] + end[2] / 2 - start[0] - start[2] / 2) * t;
  const centreY = start[1] + start[3] / 2 + (end[1] + end[3] / 2 - start[1] - start[3] / 2) * t;
  const width = start[2] * Math.pow(end[2] / start[2], t);
  const height = width * (start[3] / start[2]);
  return { x: centreX - width / 2, y: centreY - height / 2, width };
}

export function Evidence(props: GraphicInput) {
  const { resolved, input } = useMemo(() => readEvidence(props), [props]);
  const imageUrl = useBlobUrl(input.image);
  const contextUrl = useBlobUrl(input.context);
  const frame = useCurrentFrame();
  // A split shot draws in its evidence panel: the camera has the panel's shape, so the picture's
  // size is worked out from the panel and not from the frame.
  const { panel } = resolved;
  const width = panel === null ? props.width : panel.width;
  const height = panel === null ? props.height : panel.height;

  const { start, end, timeline, accent } = resolved;
  const camera = cameraAt(frame, start, end, timeline.zoom_start, timeline.zoom_end);
  const zoom = width / camera.width;
  // A world box as a box of the output frame.
  const place = (box: Box) => ({
    position: "absolute" as const,
    left: (box[0] - camera.x) * zoom,
    top: (box[1] - camera.y) * zoom,
    width: box[2] * zoom,
    height: box[3] * zoom,
  });

  // The sweep crosses the lines one after another, each for a time in proportion to its width.
  const sweep = clamp(
    (frame - timeline.sweep_start) / (timeline.sweep_end - timeline.sweep_start),
    0,
    1,
  );
  const total = resolved.rects.reduce((sum, rect) => sum + rect[2], 0);
  let before = 0;
  const bands = resolved.rects.map((rect) => {
    const share = clamp((sweep * total - before) / rect[2], 0, 1);
    before += rect[2];
    return { rect, share };
  });
  const underline = Math.max(3, Math.round(height * 0.003));

  const [badgeX, badgeY, badgeW, badgeH] = resolved.badge_box;
  const { publisher, date, page } = resolved.badge;
  const meta = [date, page === null ? null : `p. ${page}`].filter((part) => part !== null).join("  ·  ");

  // An evidence card is a rounded panel on a transparent canvas that fades in and out at its ends.
  const { card } = resolved;
  const fadeIn = card === null || card.fade_frames === 0 ? 1 : clamp(frame / card.fade_frames, 0, 1);
  const fadeOut =
    card === null || card.fade_frames === 0 ? 1 : clamp((props.frames - 1 - frame) / card.fade_frames, 0, 1);

  const content = (
    <>
      {contextUrl !== null && resolved.context_box !== null && (
        <Img src={contextUrl} style={place(resolved.context_box)} />
      )}
      {imageUrl !== null && <Img src={imageUrl} style={place(resolved.image_box)} />}
      {bands.map(({ rect, share }, index) => {
        if (share <= 0) return null;
        const box = place(rect);
        const lineWidth = box.width * share;
        return (
          <div key={index}>
            <div
              style={{
                position: "absolute",
                left: box.left - HIGHLIGHT_PAD_PX,
                top: box.top - HIGHLIGHT_PAD_PX,
                width: lineWidth + 2 * HIGHLIGHT_PAD_PX,
                height: box.height + 2 * HIGHLIGHT_PAD_PX,
                background: `${accent}66`,
                mixBlendMode: "multiply",
              }}
            />
            <div
              style={{
                position: "absolute",
                left: box.left - HIGHLIGHT_PAD_PX,
                top: box.top + box.height + HIGHLIGHT_PAD_PX,
                width: lineWidth + 2 * HIGHLIGHT_PAD_PX,
                height: underline,
                background: accent,
              }}
            />
          </div>
        );
      })}
      <div
        style={{
          position: "absolute",
          left: badgeX,
          top: badgeY,
          maxWidth: badgeW,
          height: badgeH,
          boxSizing: "border-box",
          display: "flex",
          alignItems: "center",
          gap: badgeH * 0.3,
          padding: `0 ${badgeH * 0.4}px`,
          background: BADGE_BACKGROUND,
          borderLeft: `${Math.max(4, Math.round(badgeH * 0.08))}px solid ${accent}`,
          borderRadius: badgeH * 0.18,
          opacity: clamp(frame / BADGE_FADE_FRAMES, 0, 1),
        }}
      >
        <span
          style={{
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            fontFamily: resolved.fonts.display,
            fontSize: badgeH * 0.4,
            color: BADGE_TEXT,
          }}
        >
          {publisher}
        </span>
        {meta !== "" && (
          <span
            style={{
              flexShrink: 0,
              whiteSpace: "pre",
              fontFamily: resolved.fonts.text,
              fontSize: badgeH * 0.32,
              color: BADGE_MUTED,
            }}
          >
            {meta}
          </span>
        )}
      </div>
    </>
  );

  return (
    <AbsoluteFill
      style={{
        background: resolved.background,
        overflow: "hidden",
        // A card: the rounded panel is the whole canvas, so the corners outside it stay transparent.
        ...(card === null
          ? {}
          : { borderRadius: card.radius, opacity: Math.min(fadeIn, fadeOut), isolation: "isolate" as const }),
      }}
    >
      {panel === null ? (
        content
      ) : (
        <>
          <div
            style={{
              position: "absolute",
              left: panel.x,
              top: panel.y,
              width: panel.width,
              height: panel.height,
              overflow: "hidden",
              background: resolved.background,
            }}
          >
            {content}
          </div>
          <div
            style={{
              position: "absolute",
              background: accent,
              ...(panel.edge === "top"
                ? { left: panel.x, top: panel.y - PANEL_LINE_PX / 2, width: panel.width, height: PANEL_LINE_PX }
                : { left: panel.x + panel.width - PANEL_LINE_PX / 2, top: panel.y, width: PANEL_LINE_PX, height: panel.height }),
            }}
          />
        </>
      )}
    </AbsoluteFill>
  );
}
