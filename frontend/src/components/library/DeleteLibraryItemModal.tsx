import { Alert, Button, Group, List, Loader, Modal, Stack, Text } from "@mantine/core";

import {
  useCharacterDeletionPreview,
  useDeleteCharacter,
  useDeleteEnvironment,
  useEnvironmentDeletionPreview,
} from "../../api/deletion";
import { describeError } from "../../api/errors";

type DeleteLibraryItemModalProps = {
  kind: "character" | "environment";
  libraryId: number;
  name: string;
  opened: boolean;
  onClose: () => void;
  /** Called after the item was deleted, for example to leave its page. */
  onDeleted: () => void;
};

/**
 * Asks before a library character or environment is deleted for good. It lists the projects that
 * use it: they are not changed, only flagged, and they ask the user to create it again or pick
 * another one.
 */
export function DeleteLibraryItemModal({
  kind,
  libraryId,
  name,
  opened,
  onClose,
  onDeleted,
}: DeleteLibraryItemModalProps) {
  const characterPreview = useCharacterDeletionPreview(
    opened && kind === "character" ? libraryId : null,
  );
  const environmentPreview = useEnvironmentDeletionPreview(
    opened && kind === "environment" ? libraryId : null,
  );
  const removeCharacter = useDeleteCharacter();
  const removeEnvironment = useDeleteEnvironment();

  const preview = kind === "character" ? characterPreview : environmentPreview;
  const remove = kind === "character" ? removeCharacter : removeEnvironment;
  const data = preview.data;
  const blocked = data?.blocked_reason ?? null;

  function close() {
    remove.reset();
    onClose();
  }

  function confirm() {
    remove.mutate(libraryId, {
      onSuccess: () => {
        close();
        onDeleted();
      },
    });
  }

  return (
    <Modal opened={opened} onClose={close} title={`Delete "${name}"?`} centered>
      <Stack gap="md">
        {preview.isLoading && <Loader size="sm" />}
        {preview.isError && (
          <Alert color="red" title="Could not load the projects that use it">
            {describeError(preview.error)}
          </Alert>
        )}

        {data && (
          <>
            <Text size="sm">
              This deletes the {kind}, with its versions and the pictures
              {kind === "character" ? ", speech and clips" : ""} only it uses. It cannot be
              undone.
            </Text>

            {blocked && (
              <Alert color="red" title="It cannot be deleted now">
                {blocked}
              </Alert>
            )}

            {data.projects.length > 0 ? (
              <Alert color="orange" title="Projects that use it will be flagged">
                <Stack gap="xs">
                  <List size="sm">
                    {data.projects.map((project) => (
                      <List.Item key={project.project_id}>{project.project_name}</List.Item>
                    ))}
                  </List>
                  <Text size="sm">
                    What they already made is kept. Each project shows the {kind} as deleted and
                    asks you to create it again or pick another one; the scenes and shots that
                    use it are then marked out of date and need regenerating.
                  </Text>
                </Stack>
              </Alert>
            ) : (
              <Text size="sm" c="dimmed">
                No project uses it.
              </Text>
            )}
          </>
        )}

        {remove.isError && (
          <Alert color="red" title={`The ${kind} was not deleted`}>
            {describeError(remove.error)}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button
            color="red"
            onClick={confirm}
            loading={remove.isPending}
            disabled={!data || blocked !== null}
          >
            Delete {kind}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
