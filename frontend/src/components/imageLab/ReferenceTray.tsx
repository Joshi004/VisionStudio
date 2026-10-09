import { useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  LAB_UPLOAD_MAX_MB,
  MAX_REFERENCES,
  useLabLibrary,
  useLabUpload,
  useProjectFrames,
  type LabMode,
} from "../../api/imageLab";
import { useProjects } from "../../api/projects";
import {
  addReferences,
  referenceFromFrame,
  referenceFromImage,
  type ReferenceItem,
} from "./labView";

export const ACCEPT = "image/png,image/jpeg,image/webp";

type ReferenceTrayProps = {
  items: ReferenceItem[];
  /** Takes a function of the current list, so a change made while an upload runs is not lost. */
  onChange: (update: (current: ReferenceItem[]) => ReferenceItem[]) => void;
  mode: LabMode;
};

/** A thumbnail that keeps the image's own shape. */
export function Thumb({ url, width, height }: { url: string; width: number | null; height: number | null }) {
  return (
    <img
      src={url}
      alt=""
      loading="lazy"
      style={{
        width: "100%",
        aspectRatio: width && height ? `${width} / ${height}` : "3 / 4",
        objectFit: "contain",
        background: "var(--mantine-color-gray-1)",
        borderRadius: 4,
        display: "block",
      }}
    />
  );
}

/**
 * The images that go out as references, in the order they are sent (a prompt can say "image
 * 1"). Add one by choosing a file, dropping it or pasting (Cmd+V) into the box, or pick an
 * earlier lab image, or a frame of any project.
 */
export function ReferenceTray({ items, onChange, mode }: ReferenceTrayProps) {
  const upload = useLabUpload();
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [picker, setPicker] = useState<"library" | "project" | null>(null);
  const unused = mode === "text_to_image";

  function add(added: ReferenceItem[]) {
    setNote(addReferences(items, added).note);
    onChange((current) => addReferences(current, added).items);
  }

  async function uploadAll(files: File[]) {
    setNote(null);
    upload.reset();
    const uploaded: ReferenceItem[] = [];
    for (const file of files) {
      try {
        uploaded.push(referenceFromImage(await upload.mutateAsync(file)));
      } catch {
        // The error is shown from the mutation state below. The files after it still go up.
      }
    }
    if (uploaded.length > 0) {
      add(uploaded);
    }
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    const images = Array.from(event.clipboardData.files).filter((file) =>
      file.type.startsWith("image/"),
    );
    if (images.length > 0) {
      event.preventDefault();
      void uploadAll(images);
    } else {
      setNote("The clipboard has no image. Copy an image, then paste.");
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const images = Array.from(event.dataTransfer.files).filter((file) =>
      file.type.startsWith("image/"),
    );
    if (images.length > 0) {
      void uploadAll(images);
    } else {
      setNote("Drop image files (PNG, JPEG or WebP).");
    }
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Text size="sm" fw={600}>
          Reference images ({items.length} of {MAX_REFERENCES})
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
            From earlier results
          </Button>
          <Button size="compact-sm" variant="default" onClick={() => setPicker("project")}>
            From a project
          </Button>
        </Group>
      </Group>

      {unused && (
        <Text size="xs" c="orange.8">
          Text to image sends no references. The ones listed here are kept, and sent in the other
          two modes.
        </Text>
      )}

      <div
        tabIndex={0}
        role="group"
        aria-label="Reference images. Drop images here, or click here and paste."
        onPaste={onPaste}
        onDrop={onDrop}
        onDragOver={(event) => {
          // Without this the browser would not allow a drop.
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        style={{
          border: `2px dashed var(--mantine-color-${dragging ? "blue-5" : "gray-4"})`,
          borderRadius: 8,
          padding: 12,
          background: dragging ? "var(--mantine-color-blue-0)" : undefined,
          opacity: unused ? 0.6 : 1,
        }}
      >
        {items.length === 0 ? (
          <Text size="sm" c="dimmed">
            No references. Drop images here, click here and paste (Cmd+V), or use the buttons.
          </Text>
        ) : (
          <SimpleGrid cols={{ base: 3, sm: 5, lg: 7 }} spacing="xs">
            {items.map((item, index) => (
              <Stack key={`${item.source}-${item.id}`} gap={2} style={{ position: "relative" }}>
                <Thumb url={item.url} width={item.width} height={item.height} />
                <Badge
                  size="sm"
                  variant="filled"
                  color="dark"
                  style={{ position: "absolute", top: 4, left: 4 }}
                >
                  image {index + 1}
                </Badge>
                <ActionIcon
                  size="sm"
                  variant="filled"
                  color="red"
                  aria-label={`Remove reference ${index + 1}`}
                  style={{ position: "absolute", top: 4, right: 4 }}
                  onClick={() => onChange((current) => current.filter((_, position) => position !== index))}
                >
                  x
                </ActionIcon>
                <Text size="xs" c="dimmed" lineClamp={1} title={item.label}>
                  {item.label}
                </Text>
              </Stack>
            ))}
          </SimpleGrid>
        )}
      </div>

      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          // Lets the same file be chosen again after a failed upload.
          event.currentTarget.value = "";
          if (files.length > 0) {
            void uploadAll(files);
          }
        }}
      />

      <Text size="xs" c="dimmed">
        PNG, JPEG or WebP, up to {LAB_UPLOAD_MAX_MB} MB each. A reference is sent as a JPEG, in the
        order shown.
      </Text>
      {note && (
        <Text size="xs" c="orange.8">
          {note}
        </Text>
      )}
      {upload.isError && (
        <Alert color="red" title="An image was not uploaded">
          {describeError(upload.error)}
        </Alert>
      )}

      <LibraryPicker
        opened={picker === "library"}
        onClose={() => setPicker(null)}
        onPick={(picked) => add([picked])}
      />
      <ProjectPicker
        opened={picker === "project"}
        onClose={() => setPicker(null)}
        onPick={(picked) => add([picked])}
      />
    </Stack>
  );
}

export type PickerProps = {
  opened: boolean;
  onClose: () => void;
  onPick: (item: ReferenceItem) => void;
};

export function LibraryPicker({ opened, onClose, onPick }: PickerProps) {
  const library = useLabLibrary(opened);
  return (
    <Modal opened={opened} onClose={onClose} title="From earlier results" size="xl" centered>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          The newest 60 lab images: your uploads and the results of earlier runs. Click one to add
          it.
        </Text>
        {library.isLoading && <Loader size="sm" />}
        {library.isError && (
          <Alert color="red" title="Could not load the images">
            {describeError(library.error)} Press Refresh to try again.
          </Alert>
        )}
        {library.data?.length === 0 && <Text c="dimmed">No images yet. Upload one, or make a run.</Text>}
        <SimpleGrid cols={{ base: 3, sm: 4, md: 6 }} spacing="xs">
          {library.data?.map((image) => (
            <UnstyledButton key={image.id} onClick={() => onPick(referenceFromImage(image))}>
              <Stack gap={2}>
                <Thumb url={image.url} width={image.width} height={image.height} />
                <Text size="xs" c="dimmed">
                  {image.origin === "upload" ? `upload ${image.id}` : `result of run ${image.run_id ?? "?"}`}
                </Text>
              </Stack>
            </UnstyledButton>
          ))}
        </SimpleGrid>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Done
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function ProjectPicker({ opened, onClose, onPick }: PickerProps) {
  const projects = useProjects();
  const [projectId, setProjectId] = useState<string | null>(null);
  const frames = useProjectFrames(projectId === null ? null : Number(projectId));
  return (
    <Modal opened={opened} onClose={onClose} title="From a project" size="xl" centered>
      <Stack gap="sm">
        <Select
          label="Project"
          placeholder="Choose a project"
          data={(projects.data ?? []).map((project) => ({
            value: String(project.id),
            label: project.name,
          }))}
          value={projectId}
          onChange={setProjectId}
          searchable
          nothingFoundMessage="No projects"
        />
        {projects.isError && (
          <Alert color="red" title="Could not load the projects">
            {describeError(projects.error)}
          </Alert>
        )}
        {frames.isLoading && <Loader size="sm" />}
        {frames.isError && (
          <Alert color="red" title="Could not load the frames">
            {describeError(frames.error)} Press Refresh to try again.
          </Alert>
        )}
        {frames.data?.length === 0 && <Text c="dimmed">This project has no frames.</Text>}
        {frames.data && frames.data.length > 0 && (
          <Text size="sm" c="dimmed">
            Newest first. "derived" frames are the exact files sent to the GPU server. Click one to
            add it.
          </Text>
        )}
        <SimpleGrid cols={{ base: 3, sm: 4, md: 6 }} spacing="xs">
          {frames.data?.map((frame) => (
            <UnstyledButton key={frame.asset_id} onClick={() => onPick(referenceFromFrame(frame))}>
              <Stack gap={2}>
                <Thumb url={frame.url} width={frame.width} height={frame.height} />
                <Text size="xs" c="dimmed">
                  {frame.scene_number !== null
                    ? `scene ${frame.scene_number}, ${frame.slot}`
                    : `frame ${frame.asset_id}`}{" "}
                  · {frame.source}
                </Text>
              </Stack>
            </UnstyledButton>
          ))}
        </SimpleGrid>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Done
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
