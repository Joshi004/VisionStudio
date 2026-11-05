import { Box, Text } from "@mantine/core";

import type { GraphicResolved } from "../../api/graphicsLab";

type GraphicsVideoFrameProps = {
  /** The finished video, or null while there is none (then `emptyText` is shown). */
  url: string | null;
  /** The size of every video of the run. */
  width: number;
  height: number;
  /** The safe area and the caption area are drawn from it. */
  resolved: GraphicResolved | null;
  showSafeArea: boolean;
  showCaptionArea: boolean;
  emptyText: string;
  /** The ref callback and the loaded event of the synced player (`useSyncedVideos`). */
  videoRef: (element: HTMLVideoElement | null) => void;
  onLoaded: () => void;
};

const percent = (value: number, of: number) => `${(value / of) * 100}%`;

/**
 * One video of the comparison, or an empty frame of the same shape. It has no controls of its
 * own: the run page's playback bar plays all of them together. The overlays are drawn over the
 * picture in percent of the video's size, so they line up at any width: the safe area (a dashed
 * line) and the caption area (a band the explainer's captions will use).
 */
export function GraphicsVideoFrame({
  url,
  width,
  height,
  resolved,
  showSafeArea,
  showCaptionArea,
  emptyText,
  videoRef,
  onLoaded,
}: GraphicsVideoFrameProps) {
  if (url === null) {
    return (
      <Box
        style={{
          aspectRatio: `${width} / ${height}`,
          border: "1px dashed var(--mantine-color-gray-5)",
          borderRadius: "var(--mantine-radius-sm)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text size="xs" c="dimmed" ta="center" px="xs">
          {emptyText}
        </Text>
      </Box>
    );
  }

  const safe = resolved?.safe_area;
  const caption = resolved?.caption_zone;
  return (
    <Box style={{ position: "relative", width: "100%", aspectRatio: `${width} / ${height}`, background: "black" }}>
      <video
        ref={videoRef}
        src={url}
        preload="auto"
        playsInline
        onLoadedMetadata={onLoaded}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      />
      {showCaptionArea && caption !== undefined && (
        <Box
          data-overlay="caption"
          style={{
            position: "absolute",
            left: 0,
            width: "100%",
            top: percent(caption.top, height),
            height: percent(caption.bottom - caption.top, height),
            background: "rgba(255, 176, 0, 0.25)",
            borderTop: "1px solid rgba(255, 176, 0, 0.9)",
            borderBottom: "1px solid rgba(255, 176, 0, 0.9)",
            pointerEvents: "none",
          }}
        />
      )}
      {showSafeArea && safe !== undefined && (
        <Box
          data-overlay="safe"
          style={{
            position: "absolute",
            left: percent(safe.left, width),
            top: percent(safe.top, height),
            width: percent(safe.right - safe.left, width),
            height: percent(safe.bottom - safe.top, height),
            border: "1px dashed rgba(77, 163, 255, 0.95)",
            pointerEvents: "none",
          }}
        />
      )}
    </Box>
  );
}
