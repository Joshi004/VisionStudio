import { useState } from "react";
import { Alert, Button, Group, List, Loader, Modal, Stack, Text } from "@mantine/core";

import {
  useDeleteLabSample,
  useLabSampleDeletionPreview,
  type LabSampleKind,
} from "../../api/deletion";
import { describeError } from "../../api/errors";
import { ServerCleanupCheckbox } from "../library/ServerCleanupCheckbox";

/** What the sample is called in the title of the dialog. */
const SAMPLE_NAMES: Record<LabSampleKind, string> = {
  image_run: "this image run",
  video_run: "this video run",
  voice_run: "this speech",
  music_run: "this music run",
  av_test: "this Audio video test",
};

/** What goes with the sample, said before the user confirms. */
const WHAT_GOES: Record<LabSampleKind, string> = {
  image_run: "This deletes the run, its pictures and their files.",
  video_run: "This deletes the run and its clip.",
  voice_run: "This deletes the speech and its audio file.",
  music_run: "This deletes the run and its sound file.",
  av_test:
    "This deletes the test, its clips, its two videos and its speech. A speech or a clip that a copy of the test still uses is kept.",
};

type DeleteLabSampleModalProps = {
  kind: LabSampleKind;
  sampleId: number;
  onClose: () => void;
  /** Called after the sample was deleted, for example to close the view that showed it. */
  onDeleted?: () => void;
};

/**
 * Asks before one lab sample is deleted for good. A sample that something still uses (or that is
 * still running) cannot be deleted: the dialog says why and lists where it is used. The GPU
 * server is only cleaned up when the user ticks the box.
 *
 * The dialog is shown only while it is open (its owner mounts it on demand), so the box is
 * unticked each time it opens.
 */
export function DeleteLabSampleModal({
  kind,
  sampleId,
  onClose,
  onDeleted,
}: DeleteLabSampleModalProps) {
  const preview = useLabSampleDeletionPreview(kind, sampleId);
  const remove = useDeleteLabSample();
  // Never ticked at first: the GPU server is only cleaned up when the user asks for it.
  const [purgeServer, setPurgeServer] = useState(false);

  const data = preview.data;
  const blocked = data?.blocked_reason ?? null;

  function confirm() {
    remove.mutate(
      { kind, sampleId, purgeServer },
      {
        onSuccess: () => {
          onClose();
          onDeleted?.();
        },
      },
    );
  }

  return (
    <Modal opened onClose={onClose} title={`Delete ${SAMPLE_NAMES[kind]}?`} centered>
      <Stack gap="md">
        {preview.isLoading && <Loader size="sm" />}
        {preview.isError && (
          <Alert color="red" title="Could not load where it is used">
            {describeError(preview.error)}
          </Alert>
        )}

        {data && (
          <>
            <Text size="sm" fw={600} style={{ wordBreak: "break-word" }}>
              {data.label}
            </Text>
            <Text size="sm">{WHAT_GOES[kind]} It cannot be undone.</Text>

            {blocked && (
              <Alert color="red" title="It cannot be deleted now">
                <Stack gap="xs">
                  <Text size="sm">{blocked}</Text>
                  {data.used_by.length > 0 && (
                    <List size="sm">
                      {data.used_by.map((place) => (
                        <List.Item key={place}>{place}</List.Item>
                      ))}
                    </List>
                  )}
                </Stack>
              </Alert>
            )}

            {blocked === null && (
              <ServerCleanupCheckbox
                checked={purgeServer}
                onChange={setPurgeServer}
                disabled={remove.isPending}
              />
            )}
          </>
        )}

        {remove.isError && (
          <Alert color="red" title="It was not deleted">
            {describeError(remove.error)}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button
            color="red"
            onClick={confirm}
            loading={remove.isPending}
            disabled={!data || blocked !== null}
          >
            Delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
