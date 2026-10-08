import {
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Alert, Anchor, Button, Group, LoadingOverlay, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import {
  FRAME_MAX_MB,
  useRemoveFrame,
  useUploadFrame,
  type Frame,
  type FrameSlotName,
} from "../../api/sceneInputs";
import { formatBytes } from "../../format";
import classes from "./FrameSlot.module.css";

const ACCEPT = "image/png,image/jpeg,image/webp";

const FORMAT_LABELS: Record<string, string> = {
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/webp": "WebP",
};

type FrameSlotProps = {
  project: ProjectDetail;
  sceneId: number;
  slot: FrameSlotName;
  /** What the scene holds in this slot, if anything. */
  frame: Frame | null;
  /** "First frame" or "Last frame". */
  label: string;
  /** One line of help shown under the label. */
  description?: string;
  /** Badges shown next to the label (who made the frame, whether it is out of date). */
  badge?: ReactNode;
};

/**
 * One frame of a scene. An empty slot is a button: click it to choose a file, drop an image
 * on it, or focus it and paste (Cmd+V). A filled slot shows the frame exactly as it will be
 * sent (RGB, centre-cropped, at the generation size), and takes a dropped or pasted image
 * to replace it. Every change goes to the server, which answers with the scenes.
 */
export function FrameSlot({
  project,
  sceneId,
  slot,
  frame,
  label,
  description,
  badge,
}: FrameSlotProps) {
  const upload = useUploadFrame(project.id);
  const remove = useRemoveFrame(project.id);
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [failedPreview, setFailedPreview] = useState<string | null>(null);
  const busy = upload.isPending || remove.isPending;

  function sendFile(file: File) {
    if (busy) {
      return;
    }
    setNote(null);
    remove.reset();
    upload.mutate({ sceneId, slot, file });
  }

  function openPicker() {
    if (!busy) {
      fileInput.current?.click();
    }
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    const image = Array.from(event.clipboardData.files).find((file) =>
      file.type.startsWith("image/"),
    );
    if (image) {
      event.preventDefault();
      sendFile(image);
    } else {
      setNote("The clipboard has no image. Copy an image, then paste.");
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) {
      sendFile(file);
    } else {
      setNote("Drop an image file.");
    }
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    // Without this the browser would not allow a drop.
    event.preventDefault();
    setDragging(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (frame === null && event.target === event.currentTarget) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPicker();
      }
    }
  }

  const error = upload.isError ? upload.error : remove.isError ? remove.error : null;
  const previewFailed = frame !== null && failedPreview === frame.preview_url;
  const slotClasses = [classes.slot, frame === null ? classes.empty : classes.filled];
  if (dragging) {
    slotClasses.push(classes.dragging);
  }

  return (
    <Stack gap={6}>
      <Group gap="xs">
        <Text size="sm" fw={600}>
          {label}
        </Text>
        {badge}
      </Group>
      {description && (
        <Text size="xs" c="dimmed">
          {description}
        </Text>
      )}

      <div
        className={slotClasses.join(" ")}
        style={{ aspectRatio: `${project.gen_width} / ${project.gen_height}` }}
        role={frame === null ? "button" : "group"}
        tabIndex={0}
        aria-label={
          frame === null
            ? `${label}: empty. Click to choose an image, drop one here, or paste one.`
            : `${label}. Drop or paste an image here to replace it.`
        }
        onClick={frame === null ? openPicker : undefined}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={() => setDragging(false)}
      >
        <LoadingOverlay visible={busy} zIndex={5} loaderProps={{ size: "sm" }} />
        {frame === null ? (
          <Text size="sm" c="dimmed">
            Click to choose an image, drop one here, or click here and paste (Cmd+V).
          </Text>
        ) : previewFailed ? (
          <Text size="sm" c="red" p="sm">
            The preview could not be loaded. Press Refresh.
          </Text>
        ) : (
          <img
            className={classes.preview}
            src={frame.preview_url}
            alt={`${label}, as it will be sent`}
            onError={() => setFailedPreview(frame.preview_url)}
          />
        )}
      </div>

      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          // Lets the same file be chosen again after a failed upload.
          event.currentTarget.value = "";
          if (file) {
            sendFile(file);
          }
        }}
      />

      {frame !== null && (
        <>
          <Text size="xs" c="dimmed">
            {frame.width !== null && frame.height !== null
              ? `Original ${frame.width} x ${frame.height} · `
              : "Original · "}
            {FORMAT_LABELS[frame.mime] ?? frame.mime} · {formatBytes(frame.size_bytes)} ·{" "}
            <Anchor href={frame.original_url} target="_blank" rel="noreferrer" size="xs">
              Open the original
            </Anchor>
          </Text>
          {frame.warnings.map((warning) => (
            <Text key={warning} size="xs" c="orange.8">
              {warning}
            </Text>
          ))}
          <Group gap="xs">
            <Button size="compact-xs" variant="default" disabled={busy} onClick={openPicker}>
              Replace
            </Button>
            <Button
              size="compact-xs"
              color="red"
              variant="light"
              disabled={busy}
              onClick={() => {
                setNote(null);
                upload.reset();
                remove.mutate({ sceneId, slot });
              }}
            >
              Remove
            </Button>
          </Group>
        </>
      )}

      {frame === null && (
        <Text size="xs" c="dimmed">
          PNG, JPEG or WebP, up to {FRAME_MAX_MB} MB.
        </Text>
      )}
      {note && (
        <Text size="xs" c="orange.8">
          {note}
        </Text>
      )}
      {error && (
        <Alert color="red" title={upload.isError ? "The frame was not saved" : "The frame was not removed"}>
          {describeError(error)}
        </Alert>
      )}
    </Stack>
  );
}
