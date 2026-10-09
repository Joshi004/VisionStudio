import { useRef, useState } from "react";
import { Alert, Button, Group, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { LAB_UPLOAD_MAX_MB, useLabUpload } from "../../api/imageLab";
import { ACCEPT, LibraryPicker, ProjectPicker, Thumb } from "../imageLab/ReferenceTray";
import { referenceFromImage, type ReferenceItem } from "../imageLab/labView";

type FirstFramePickerProps = {
  value: ReferenceItem | null;
  onChange: (value: ReferenceItem | null) => void;
};

/**
 * The image a clip starts from (optional: without one the clip is made from the prompt alone).
 * Upload a file, pick an earlier Image lab result or upload, or take a frame of any project.
 * The image is cut to the clip's shape (centred) and sent as the clip's literal first frame.
 */
export function FirstFramePicker({ value, onChange }: FirstFramePickerProps) {
  const upload = useLabUpload();
  const fileInput = useRef<HTMLInputElement>(null);
  const [picker, setPicker] = useState<"library" | "project" | null>(null);

  async function uploadFile(file: File) {
    upload.reset();
    try {
      onChange(referenceFromImage(await upload.mutateAsync(file)));
    } catch {
      // The error is shown from the mutation state below.
    }
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Text size="sm" fw={600}>
          First frame (optional)
        </Text>
        <Group gap="xs">
          <Button
            size="compact-sm"
            variant="default"
            loading={upload.isPending}
            onClick={() => fileInput.current?.click()}
          >
            Upload
          </Button>
          <Button size="compact-sm" variant="default" onClick={() => setPicker("library")}>
            From the Image lab
          </Button>
          <Button size="compact-sm" variant="default" onClick={() => setPicker("project")}>
            From a project
          </Button>
          {value !== null && (
            <Button size="compact-sm" variant="subtle" color="red" onClick={() => onChange(null)}>
              Remove
            </Button>
          )}
        </Group>
      </Group>

      {value === null ? (
        <Text size="sm" c="dimmed">
          No first frame: the clip is made from the prompt alone (text-to-video).
        </Text>
      ) : (
        <Group gap="sm" align="flex-start" wrap="nowrap">
          <div style={{ width: 96, flexShrink: 0 }}>
            <Thumb url={value.url} width={value.width} height={value.height} />
          </div>
          <Stack gap={2}>
            <Text size="sm">{value.label}</Text>
            <Text size="xs" c="dimmed">
              The clip starts on this image, so describe only what moves, the camera and the
              sound. With LTX-2.5, write the cuts after that opening shot.
            </Text>
          </Stack>
        </Group>
      )}

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
            void uploadFile(file);
          }
        }}
      />
      <Text size="xs" c="dimmed">
        PNG, JPEG or WebP, up to {LAB_UPLOAD_MAX_MB} MB.
      </Text>
      {upload.isError && (
        <Alert color="red" title="The image was not uploaded">
          {describeError(upload.error)}
        </Alert>
      )}

      <LibraryPicker
        opened={picker === "library"}
        onClose={() => setPicker(null)}
        onPick={(picked) => {
          onChange(picked);
          setPicker(null);
        }}
      />
      <ProjectPicker
        opened={picker === "project"}
        onClose={() => setPicker(null)}
        onPick={(picked) => {
          onChange(picked);
          setPicker(null);
        }}
      />
    </Stack>
  );
}
