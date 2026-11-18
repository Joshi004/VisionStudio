import { useState } from "react";

import { Button, Group, Stack, Switch, Text } from "@mantine/core";

import { isJobActive } from "../../api/polling";
import type { EvidenceReviewItem } from "../../api/evidence";

type EvidencePreviewProps = {
  item: EvidenceReviewItem;
  disabled: boolean;
  starting: boolean;
  onStart: () => void;
};

/**
 * Whether the quote's text will be big enough to read in the video. It is worked out from the
 * capture's rectangles, so it shows before any preview is drawn.
 */
export function ReadabilityWarning({ item }: { item: EvidenceReviewItem }) {
  const readability = item.readability;
  if (!item.usable || readability === null || readability.ok) {
    return null;
  }
  return (
    <Text size="xs" c="orange">
      The quote&apos;s text will be about {Math.round(readability.text_height_px)} px tall in the
      video; at least {Math.round(readability.min_px)} px is needed to read it. Pick a shorter
      quote, or a source with larger text.
    </Text>
  );
}

/**
 * The preview video of an accepted piece: a button to draw it, and the video once it exists. The
 * caption area can be drawn over the video, to see that nothing highlighted is under the captions.
 */
export function EvidencePreview({ item, disabled, starting, onStart }: EvidencePreviewProps) {
  const [showCaptions, setShowCaptions] = useState(false);
  const preview = item.preview;
  const active = isJobActive(preview);

  return (
    <Stack gap={4} align="flex-start">
      <Group gap="sm">
        <Button
          size="xs"
          variant="light"
          loading={starting || active}
          disabled={disabled}
          onClick={onStart}
        >
          {preview === null ? "Preview video" : "Preview again"}
        </Button>
        {preview?.status === "queued" && (
          <Text size="xs" c="dimmed">
            Waiting to start
          </Text>
        )}
        {preview?.status === "running" && (
          <Text size="xs" c="dimmed">
            Drawing the video
          </Text>
        )}
      </Group>

      {preview?.status === "failed" && (
        <Text size="xs" c="red">
          The preview could not be drawn{preview.error !== null ? `: ${preview.error}` : "."}
        </Text>
      )}
      {preview?.status === "cancelled" && (
        <Text size="xs" c="dimmed">
          The preview was cancelled.
        </Text>
      )}

      {preview?.video_url != null && (
        <Stack gap={4} align="flex-start">
          {preview.out_of_date && (
            <Text size="xs" c="orange">
              This preview was drawn with another colour, size or length than a new one would be.
              Press Preview again to see how it looks now.
            </Text>
          )}
          <div style={{ position: "relative", display: "inline-block", lineHeight: 0 }}>
            <video
              src={preview.video_url}
              controls
              preload="metadata"
              style={{
                display: "block",
                maxWidth: "100%",
                maxHeight: 360,
                aspectRatio: `${preview.width} / ${preview.height}`,
                background: "#000",
              }}
            />
            {showCaptions && (
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  top: `${preview.caption_top * 100}%`,
                  height: `${(preview.caption_bottom - preview.caption_top) * 100}%`,
                  boxSizing: "border-box",
                  border: "1px dashed rgba(255, 255, 255, 0.9)",
                  backgroundColor: "rgba(0, 0, 0, 0.3)",
                  pointerEvents: "none",
                }}
              />
            )}
          </div>
          <Switch
            size="xs"
            label="Show caption area"
            checked={showCaptions}
            onChange={(event) => setShowCaptions(event.currentTarget.checked)}
          />
          {preview.warnings.map((text) => (
            <Text key={text} size="xs" c="orange">
              {text}
            </Text>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
