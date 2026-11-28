import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  FileButton,
  Group,
  Loader,
  NumberInput,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  FOOTAGE_CREDIT_MAX_CHARS,
  FOOTAGE_FILE_ACCEPT,
  FOOTAGE_USE_STEP_S,
  useRemoveFootageFile,
  useReorderFootageFiles,
  useSetFootageUse,
  useStartFootagePreview,
  useUploadFootageFile,
  type FootageFile,
} from "../../api/footageFiles";
import { FootagePreview } from "./FootagePreview";

/** The most files of the owner's one mark holds (the server enforces it). */
const MAX_FILES = 9;
const THUMB_W = 96;
const THUMB_H = 54;

type Props = {
  projectId: number;
  markId: string;
  /** The files shown on this mark, in the order shown. */
  files: FootageFile[];
};

/** A small picture of a file: the photo itself, or the first frame of a video's strip. */
function Thumbnail({ file }: { file: FootageFile }) {
  const box = {
    width: THUMB_W,
    height: THUMB_H,
    flex: "none",
    borderRadius: 4,
    background: "var(--mantine-color-dark-6)",
  } as const;
  if (file.kind === "image" && file.media_url) {
    return (
      <div
        role="img"
        aria-label="Your photo"
        style={{
          ...box,
          backgroundImage: `url(${file.media_url})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />
    );
  }
  if (file.kind === "video" && file.strip_url && file.strip) {
    return (
      <div
        role="img"
        aria-label="The first frame of your video"
        style={{
          ...box,
          backgroundImage: `url(${file.strip_url})`,
          backgroundSize: `${file.strip.columns * THUMB_W}px ${file.strip.rows * THUMB_H}px`,
          backgroundPosition: "0 0",
        }}
      />
    );
  }
  return <div style={box} />;
}

type RangeProps = {
  file: FootageFile;
  disabled: boolean;
  onChange: (startS: number, endS: number) => void;
};

/** Where a ready video starts and ends, in steps of half a second, with a muted preview of it. */
function VideoRange({ file, disabled, onChange }: RangeProps) {
  const use = file.use;
  const duration = file.duration_s;
  const [start, setStart] = useState<number | string>(use?.start_s ?? 0);
  const [end, setEnd] = useState<number | string>(use?.end_s ?? 0);
  if (!use || duration === null || !file.media_url) {
    return null;
  }

  function commit() {
    if (typeof start === "number" && typeof end === "number") {
      if (start !== use?.start_s || end !== use?.end_s) {
        onChange(start, end);
      }
    }
  }

  return (
    <Stack gap={4}>
      <Group gap="xs" wrap="nowrap">
        <NumberInput
          size="xs"
          w={110}
          label="Starts at (s)"
          min={0}
          max={duration}
          step={FOOTAGE_USE_STEP_S}
          decimalScale={1}
          fixedDecimalScale
          value={start}
          disabled={disabled}
          onChange={setStart}
          onBlur={commit}
        />
        <NumberInput
          size="xs"
          w={110}
          label="Ends at (s)"
          min={0}
          max={duration}
          step={FOOTAGE_USE_STEP_S}
          decimalScale={1}
          fixedDecimalScale
          value={end}
          disabled={disabled}
          onChange={setEnd}
          onBlur={commit}
        />
        <Text size="xs" c="dimmed" pt={18}>
          of {duration.toFixed(1)} s
        </Text>
      </Group>
      <video
        src={`${file.media_url}#t=${use.start_s},${use.end_s}`}
        controls
        muted
        preload="metadata"
        style={{ maxWidth: 240, maxHeight: 135, borderRadius: 4 }}
      />
    </Stack>
  );
}

type RowProps = {
  file: FootageFile;
  first: boolean;
  last: boolean;
  disabled: boolean;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
  onUse: (startS: number, endS: number) => void;
  previewStarting: boolean;
  onPreview: () => void;
};

function FileRow({
  file,
  first,
  last,
  disabled,
  onMove,
  onRemove,
  onUse,
  previewStarting,
  onPreview,
}: RowProps) {
  return (
    <Stack gap={4}>
      <Group gap="xs" wrap="nowrap" align="flex-start">
        <Thumbnail file={file} />
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs">
            <Badge variant="light" color="gray">
              {file.kind === "image" ? "Photo" : "Video"}
            </Badge>
            {file.status === "preparing" && (
              <Group gap={4}>
                <Loader size="xs" />
                <Text size="xs" c="dimmed">
                  Getting the video ready
                </Text>
              </Group>
            )}
            {file.status === "ready" && (
              <Badge variant="light" color="green">
                Ready
              </Badge>
            )}
            {file.status === "failed" && (
              <Badge variant="light" color="red">
                Not ready
              </Badge>
            )}
          </Group>
          {file.credit && (
            <Text size="xs" c="dimmed" truncate>
              Credit: {file.credit}
            </Text>
          )}
          {file.status === "failed" && (
            <Text size="xs" c="red">
              {file.error ?? "The file could not be made ready."} Remove it and add it again.
            </Text>
          )}
        </Stack>
        <Group gap={4} wrap="nowrap">
          <Button
            size="compact-xs"
            variant="default"
            aria-label="Show this file earlier"
            disabled={disabled || first}
            onClick={() => onMove(-1)}
          >
            Up
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            aria-label="Show this file later"
            disabled={disabled || last}
            onClick={() => onMove(1)}
          >
            Down
          </Button>
          <Button size="compact-xs" variant="default" disabled={disabled} onClick={onRemove}>
            Remove
          </Button>
        </Group>
      </Group>
      {file.kind === "video" && file.status === "ready" && (
        <VideoRange
          // A new start or end from the server resets the boxes.
          key={`${file.item_key}-${file.use?.start_s}-${file.use?.end_s}`}
          file={file}
          disabled={disabled}
          onChange={onUse}
        />
      )}
      {file.status === "ready" && (
        <FootagePreview
          preview={file.preview}
          disabled={disabled}
          starting={previewStarting}
          onStart={onPreview}
        />
      )}
    </Stack>
  );
}

/**
 * The owner's own photos and videos on a footage mark (FTG-003): add one, take one off, change
 * the order they are shown in, and for a video choose where it starts and ends. A file is
 * accepted when it is added.
 */
export function FootageFilesSection({ projectId, markId, files }: Props) {
  const upload = useUploadFootageFile(projectId);
  const remove = useRemoveFootageFile(projectId);
  const reorder = useReorderFootageFiles(projectId);
  const setUse = useSetFootageUse(projectId);
  const startPreview = useStartFootagePreview(projectId);
  const [credit, setCredit] = useState("");

  const pending = upload.isPending || remove.isPending || reorder.isPending || setUse.isPending;

  function resetErrors() {
    upload.reset();
    remove.reset();
    reorder.reset();
    setUse.reset();
    startPreview.reset();
  }

  function move(index: number, direction: -1 | 1) {
    resetErrors();
    const keys = files.map((file) => file.item_key);
    const target = index + direction;
    [keys[index], keys[target]] = [keys[target], keys[index]];
    reorder.mutate({ markId, shown: keys });
  }

  return (
    <Stack gap="xs" onClick={(event) => event.stopPropagation()}>
      <Text size="xs" fw={600}>
        Your files
      </Text>
      {files.length === 0 && (
        <Text size="xs" c="dimmed">
          None. Add a photo or a video of your own to show instead of searching for footage.
        </Text>
      )}
      {files.map((file, index) => (
        <FileRow
          key={file.item_key}
          file={file}
          first={index === 0}
          last={index === files.length - 1}
          disabled={pending}
          onMove={(direction) => move(index, direction)}
          onRemove={() => {
            resetErrors();
            remove.mutate(file.item_key);
          }}
          onUse={(startS, endS) => {
            resetErrors();
            setUse.mutate({ itemKey: file.item_key, startS, endS });
          }}
          previewStarting={startPreview.isPending && startPreview.variables === file.item_key}
          onPreview={() => {
            resetErrors();
            startPreview.mutate(file.item_key);
          }}
        />
      ))}
      <Group gap="xs" wrap="nowrap" align="flex-end">
        <TextInput
          size="xs"
          style={{ flex: 1 }}
          aria-label="Credit for the next file"
          placeholder="Credit to show for the next file (optional)"
          maxLength={FOOTAGE_CREDIT_MAX_CHARS}
          value={credit}
          disabled={pending}
          onChange={(event) => setCredit(event.currentTarget.value)}
        />
        <FileButton
          accept={FOOTAGE_FILE_ACCEPT}
          onChange={(file) => {
            if (file) {
              resetErrors();
              upload.mutate({ markId, file, credit }, { onSuccess: () => setCredit("") });
            }
          }}
        >
          {(props) => (
            <Button
              {...props}
              size="compact-sm"
              variant="default"
              loading={upload.isPending}
              disabled={pending || files.length >= MAX_FILES}
            >
              Add a photo or video
            </Button>
          )}
        </FileButton>
      </Group>
      {upload.isError && (
        <Alert color="red" p="xs" title="The file was not added">
          {describeError(upload.error)}
        </Alert>
      )}
      {remove.isError && (
        <Alert color="red" p="xs" title="The file was not removed">
          {describeError(remove.error)}
        </Alert>
      )}
      {reorder.isError && (
        <Alert color="red" p="xs" title="The order was not changed">
          {describeError(reorder.error)}
        </Alert>
      )}
      {startPreview.isError && (
        <Alert color="red" p="xs" title="The preview was not started">
          {describeError(startPreview.error)}
        </Alert>
      )}
      {setUse.isError && (
        <Alert color="red" p="xs" title="The start and end were not changed">
          {describeError(setUse.error)}
        </Alert>
      )}
    </Stack>
  );
}
