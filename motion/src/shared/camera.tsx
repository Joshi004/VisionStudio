import { useEffect, useState } from "react";

// What the evidence clip (EVD-008) and the footage clip (FTG-005) share: a picture that travels in
// the request, a camera that moves over a flat world, and the highlight that sweeps over lines of
// it. The backend decides every box and every frame (`evidence_clip_layout.py`,
// `footage_clip_layout.py`); this file only draws them. Every pixel depends only on the frame number.

// A box of the picture's world, `[x, y, width, height]` in the picture's own pixels.
export type Box = [number, number, number, number];

export type ImagePayload = { mime: "image/png" | "image/jpeg"; base64: string };

// How much of the line's height the highlight reaches above and below the text, in output pixels.
export const HIGHLIGHT_PAD_PX = 2;

export const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
export const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function blobUrl(image: ImagePayload): string {
  const binary = atob(image.base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return URL.createObjectURL(new Blob([bytes], { type: image.mime }));
}

// An address for a picture of the request, made once and let go of when the composition goes. A
// blob address avoids any limit a browser puts on the length of a `data:` address.
export function useBlobUrl(image: ImagePayload | null): string | null {
  const [url] = useState(() => (image === null ? null : blobUrl(image)));
  useEffect(
    () => () => {
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );
  return url;
}

export type Camera = { x: number; y: number; width: number };

// The camera's place at a frame: its middle moves in a straight line, its width by the same ratio
// every frame (so the zoom looks even), both eased.
export function cameraAt(frame: number, start: Box, end: Box, zoomStart: number, zoomEnd: number): Camera {
  const t = easeInOut(clamp((frame - zoomStart) / (zoomEnd - zoomStart), 0, 1));
  const centreX = start[0] + start[2] / 2 + (end[0] + end[2] / 2 - start[0] - start[2] / 2) * t;
  const centreY = start[1] + start[3] / 2 + (end[1] + end[3] / 2 - start[1] - start[3] / 2) * t;
  const width = start[2] * Math.pow(end[2] / start[2], t);
  const height = width * (start[3] / start[2]);
  return { x: centreX - width / 2, y: centreY - height / 2, width };
}

// A world box as a box of the area the world is drawn in, for a camera and that area's width.
export type Place = (box: Box) => { position: "absolute"; left: number; top: number; width: number; height: number };

export function placeFor(camera: Camera, areaWidth: number): Place {
  const zoom = areaWidth / camera.width;
  return (box) => ({
    position: "absolute",
    left: (box[0] - camera.x) * zoom,
    top: (box[1] - camera.y) * zoom,
    width: box[2] * zoom,
    height: box[3] * zoom,
  });
}

// The sweep crosses the lines one after another, each for a time in proportion to its width.
export function sweepBands(rects: Box[], sweep: number): { rect: Box; share: number }[] {
  const total = rects.reduce((sum, rect) => sum + rect[2], 0);
  let before = 0;
  return rects.map((rect) => {
    const share = clamp((sweep * total - before) / rect[2], 0, 1);
    before += rect[2];
    return { rect, share };
  });
}

// The highlight over the lines the sweep has reached: a translucent band in the accent colour and an
// underline. `height` is the clip's height, which sets the underline's thickness.
export function Highlights(props: {
  bands: { rect: Box; share: number }[];
  place: Place;
  accent: string;
  height: number;
}) {
  const underline = Math.max(3, Math.round(props.height * 0.003));
  return (
    <>
      {props.bands.map(({ rect, share }, index) => {
        if (share <= 0) return null;
        const box = props.place(rect);
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
                background: `${props.accent}66`,
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
                background: props.accent,
              }}
            />
          </div>
        );
      })}
    </>
  );
}
