import { useEffect, useRef, useState } from "react";
import { Alert, Button, FileButton, Group, Loader, Text } from "@mantine/core";

import { useDescribePhoto, type PhotoMode } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { LAB_UPLOAD_MAX_MB, useLabUpload } from "../../api/imageLab";
import { useJob } from "../../api/jobs";
import { ACCEPT } from "../imageLab/ReferenceTray";

/** The text a finished `describe_photo` job wrote, or null while it has none. */
function fieldsOf(output: unknown): Record<string, string> | null {
  if (typeof output !== "object" || output === null || !("fields" in output)) {
    return null;
  }
  const fields = output.fields;
  if (typeof fields !== "object" || fields === null) {
    return null;
  }
  const found: Record<string, string> = {};
  for (const [key, value] of Object.entries(fields)) {
    if (typeof value === "string") {
      found[key] = value;
    }
  }
  return found;
}

type FillFromPhotoProps = {
  mode: PhotoMode;
  /** Called with the text the model wrote, once. The caller decides which boxes to fill. */
  onFilled: (fields: Record<string, string>) => void;
  /** Called with the uploaded photo's id, so the photo can be reused (for the look). */
  onPhoto?: (imageId: number) => void;
};

/**
 * Lets the owner choose a photo and have the vision model fill in the text boxes from it
 * (a paid call, made only when the owner chooses a photo). Nothing is saved: the text only goes
 * into the boxes, where it can be read and changed.
 */
export function FillFromPhoto({ mode, onFilled, onPhoto }: FillFromPhotoProps) {
  const upload = useLabUpload();
  const describe = useDescribePhoto();
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(jobId);
  const resetFileButton = useRef<() => void>(null);
  const filledJob = useRef<number | null>(null);

  const status = job.data?.status;
  const working =
    upload.isPending || describe.isPending || status === "queued" || status === "running";
  const failed = status === "failed" || status === "cancelled";
  const fields = status === "succeeded" ? fieldsOf(job.data?.output) : null;

  useEffect(() => {
    if (fields !== null && jobId !== null && filledJob.current !== jobId) {
      filledJob.current = jobId;
      onFilled(fields);
    }
  }, [fields, jobId, onFilled]);

  function choose(file: File | null) {
    resetFileButton.current?.();
    if (file === null) {
      return;
    }
    upload.mutate(file, {
      onSuccess: (image) => {
        onPhoto?.(image.id);
        describe.mutate(
          { imageId: image.id, mode },
          { onSuccess: (started) => setJobId(started.id) },
        );
      },
    });
  }

  const error = upload.isError ? upload.error : describe.isError ? describe.error : null;

  return (
    <Group gap="xs" align="center">
      <FileButton resetRef={resetFileButton} onChange={choose} accept={ACCEPT}>
        {(props) => (
          <Button {...props} size="compact-sm" variant="light" disabled={working}>
            Fill from photo
          </Button>
        )}
      </FileButton>
      {working && <Loader size="xs" />}
      <Text size="xs" c="dimmed">
        {working
          ? "Reading the photo..."
          : `Optional. A photo (up to ${LAB_UPLOAD_MAX_MB} MB) fills the empty boxes; you can change the text. One call to the vision model.`}
      </Text>
      {error !== null && (
        <Alert color="red" p="xs" style={{ width: "100%" }}>
          {describeError(error)}
        </Alert>
      )}
      {failed && (
        <Alert color="red" p="xs" style={{ width: "100%" }}>
          {job.data?.error ?? "The photo could not be read."}
        </Alert>
      )}
    </Group>
  );
}
