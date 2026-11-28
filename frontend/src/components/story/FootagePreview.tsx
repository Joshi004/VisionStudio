import { Button, Group, Stack, Text } from "@mantine/core";

import type { FootageFile } from "../../api/footageFiles";
import { isJobActive } from "../../api/polling";

type FootagePreviewProps = {
  file: FootageFile;
  disabled: boolean;
  starting: boolean;
  onStart: () => void;
};

/**
 * The preview video of a ready file (FTG-005): a button to draw 6 seconds of it the way it will
 * be laid over the shots, and the video once it exists.
 */
export function FootagePreview({ file, disabled, starting, onStart }: FootagePreviewProps) {
  const preview = file.preview;
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
              This preview was drawn with other settings than a new one would be. Press Preview
              again to see how it looks now.
            </Text>
          )}
          <video
            src={preview.video_url}
            controls
            muted
            preload="metadata"
            style={{
              display: "block",
              maxWidth: "100%",
              maxHeight: 360,
              aspectRatio: `${preview.width} / ${preview.height}`,
              background: "#000",
            }}
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
