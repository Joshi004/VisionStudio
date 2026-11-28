import { useMemo } from "react";
import { AbsoluteFill, Img, useCurrentFrame } from "remotion";

import { cameraAt, clamp, Highlights, placeFor, sweepBands, useBlobUrl } from "../shared/camera";
import type { Box } from "../shared/camera";
import type { GraphicInput } from "../types";
import { readFootage } from "./props";
import type { FootageResolved } from "./props";

// The footage clip of FTG-005 (`Footage_broll_implementation_phases.md` §4.10): a still picture
// laid full screen over the shots under a mark's words. Three modes, all decided by the backend
// (`footage_clip_layout.py`):
//
// - `image`: a photo that fills the frame, or is fitted over a blurred, darkened copy of itself,
//   with a slow zoom of the whole frame.
// - `page`: a web page in a browser window with its address; the camera scrolls from the top of the
//   page to the focus, zooms in, and the highlight sweeps over the focus words.
// - `pdf`: one page of a PDF on the plain background, with a zoom to the focus and its highlight.
//
// There is no sound and no badge: the credit line is a caption (FTG-006). Every pixel depends only
// on the frame number.

const WINDOW_BACKGROUND = "#262B36";
const WINDOW_SHADOW = "0 12px 40px rgba(0, 0, 0, 0.5)";
const ADDRESS_BACKGROUND = "#14181F";
const ADDRESS_TEXT = "#C9D1DC";
const PAGE_BACKGROUND = "#FFFFFF";
const DOTS = ["#FF5F57", "#FEBC2E", "#28C840"];

const boxStyle = (box: Box) => ({
  position: "absolute" as const,
  left: box[0],
  top: box[1],
  width: box[2],
  height: box[3],
});

function ImageMode({ resolved, url, frames }: { resolved: FootageResolved; url: string; frames: number }) {
  const frame = useCurrentFrame();
  const look = resolved.image!;
  const progress = frames > 1 ? clamp(frame / (frames - 1), 0, 1) : 0;
  const zoom = 1 + (look.zoom_end - 1) * progress;
  return (
    <AbsoluteFill style={{ background: resolved.background, overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: "50% 50%" }}>
        {look.backdrop !== null && (
          <Img
            src={url}
            style={{
              ...boxStyle(look.backdrop),
              filter: `blur(${resolved.blur_sigma}px) brightness(${resolved.darken})`,
            }}
          />
        )}
        <Img src={url} style={boxStyle(look.picture)} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

function CameraMode({ resolved, url, height }: { resolved: FootageResolved; url: string; height: number }) {
  const frame = useCurrentFrame();
  const { view, start, end, timeline, accent } = resolved;
  const camera = cameraAt(frame, start!, end!, timeline!.zoom_start, timeline!.zoom_end);
  const place = placeFor(camera, view![2]);
  const world: Box = [0, 0, resolved.image_px[0], resolved.image_px[1]];
  const sweep =
    timeline!.sweep_start === null || timeline!.sweep_end === null
      ? 0
      : clamp((frame - timeline!.sweep_start) / (timeline!.sweep_end - timeline!.sweep_start), 0, 1);
  const bands = sweepBands(resolved.rects, sweep);
  const page = resolved.mode === "page";

  const picture = (
    <>
      {!page && (
        <div
          style={{
            ...place(world),
            background: PAGE_BACKGROUND,
            boxShadow: `0 0 ${Math.round(view![2] / camera.width * 30)}px rgba(0, 0, 0, 0.55)`,
          }}
        />
      )}
      <Img src={url} style={place(world)} />
      <Highlights bands={bands} place={place} accent={accent} height={height} />
    </>
  );

  if (!page) {
    return (
      <AbsoluteFill style={{ background: resolved.background, overflow: "hidden" }}>{picture}</AbsoluteFill>
    );
  }

  const chrome = resolved.window!;
  const [windowX, windowY, windowW, windowH] = chrome.box;
  const bar = chrome.bar_height;
  const dot = bar * 0.3;
  const pill = bar * 0.62;
  const dotsWidth = bar * 0.5 + DOTS.length * dot * 1.6;
  return (
    <AbsoluteFill style={{ background: resolved.background, overflow: "hidden" }}>
      <div
        style={{
          ...boxStyle([windowX, windowY, windowW, windowH]),
          borderRadius: chrome.radius,
          overflow: "hidden",
          background: WINDOW_BACKGROUND,
          boxShadow: WINDOW_SHADOW,
        }}
      >
        <div style={{ position: "absolute", left: 0, top: 0, width: windowW, height: bar }}>
          {DOTS.map((colour, index) => (
            <div
              key={colour}
              style={{
                position: "absolute",
                left: bar * 0.4 + index * dot * 1.6,
                top: (bar - dot) / 2,
                width: dot,
                height: dot,
                borderRadius: dot / 2,
                background: colour,
              }}
            />
          ))}
          <div
            style={{
              position: "absolute",
              left: dotsWidth + bar * 0.3,
              top: (bar - pill) / 2,
              width: windowW - dotsWidth - bar * 0.3 - bar * 0.5,
              height: pill,
              borderRadius: pill / 2,
              background: ADDRESS_BACKGROUND,
              display: "flex",
              alignItems: "center",
              padding: `0 ${pill * 0.5}px`,
              boxSizing: "border-box",
              overflow: "hidden",
            }}
          >
            <span
              style={{
                minWidth: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                fontFamily: resolved.fonts.text,
                fontSize: pill * 0.5,
                color: ADDRESS_TEXT,
              }}
            >
              {chrome.address}
            </span>
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: bar,
            width: windowW,
            height: windowH - bar,
            overflow: "hidden",
            background: PAGE_BACKGROUND,
          }}
        >
          {picture}
        </div>
      </div>
    </AbsoluteFill>
  );
}

export function Footage(props: GraphicInput) {
  const { resolved, image } = useMemo(() => readFootage(props), [props]);
  const url = useBlobUrl(image);
  if (url === null) return null;
  return resolved.mode === "image" ? (
    <ImageMode resolved={resolved} url={url} frames={props.frames} />
  ) : (
    <CameraMode resolved={resolved} url={url} height={props.height} />
  );
}
