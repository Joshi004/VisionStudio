import { Alert, Button, Checkbox, Group, Loader, Modal, Stack, Text } from "@mantine/core";
import { useState } from "react";

import {
  useDeleteProject,
  useProjectDeletionPreview,
  type DeletionItem,
} from "../../api/deletion";
import { describeError } from "../../api/errors";

type DeleteProjectModalProps = {
  /** The project to delete, or null while the dialog is closed. */
  project: { id: number; name: string } | null;
  onClose: () => void;
  /** Called after the project was deleted. */
  onDeleted?: () => void;
};

const HOW: Record<DeletionItem["how"], string> = {
  created: "made for this project",
  mapped: "chosen from the library",
  cast: "in this project's cast",
  made_for_project: "made for this project earlier",
};

/** The ids of the items that can be deleted and were not unticked. */
function ticked(items: DeletionItem[], unticked: Set<number>): Set<number> {
  return new Set(
    items
      .filter((item) => item.blocked_reason === null && !unticked.has(item.library_id))
      .map((item) => item.library_id),
  );
}

/** The ids of the items that can be deleted and are not in `selected`. */
function unticked(items: DeletionItem[], selected: Set<number>): Set<number> {
  return new Set(
    items
      .filter((item) => item.blocked_reason === null && !selected.has(item.library_id))
      .map((item) => item.library_id),
  );
}

type ItemListProps = {
  title: string;
  items: DeletionItem[];
  selected: Set<number>;
  onChange: (selected: Set<number>) => void;
};

/** The deletable items can be ticked; one that cannot be deleted now is shown with the reason. */
function ItemList({ title, items, selected, onChange }: ItemListProps) {
  if (items.length === 0) {
    return null;
  }
  const deletable = items.filter((item) => item.blocked_reason === null);
  const allSelected = deletable.length > 0 && deletable.every((item) => selected.has(item.library_id));
  const someSelected = deletable.some((item) => selected.has(item.library_id));

  function toggle(libraryId: number, checked: boolean) {
    const next = new Set(selected);
    if (checked) {
      next.add(libraryId);
    } else {
      next.delete(libraryId);
    }
    onChange(next);
  }

  return (
    <Stack gap="xs">
      <Checkbox
        label={<Text fw={600}>{title}</Text>}
        checked={allSelected}
        indeterminate={someSelected && !allSelected}
        disabled={deletable.length === 0}
        onChange={(event) =>
          onChange(
            event.currentTarget.checked
              ? new Set(deletable.map((item) => item.library_id))
              : new Set(),
          )
        }
      />
      <Stack gap="xs" pl="md">
        {items.map((item) => (
          <Checkbox
            key={item.library_id}
            checked={selected.has(item.library_id)}
            disabled={item.blocked_reason !== null}
            onChange={(event) => toggle(item.library_id, event.currentTarget.checked)}
            label={
              <Text size="sm">
                {item.name}{" "}
                <Text span size="xs" c="dimmed">
                  ({HOW[item.how]}
                  {item.archived ? ", archived" : ""})
                </Text>
              </Text>
            }
            description={
              item.blocked_reason !== null ? (
                <Text span size="xs" c="red">
                  {item.blocked_reason}
                </Text>
              ) : item.other_projects.length > 0 ? (
                <Text span size="xs" c="orange">
                  Also used in {item.other_projects.join(", ")}. Those projects will be flagged:
                  they will have to create it again, and what was made with it needs
                  regenerating.
                </Text>
              ) : undefined
            }
          />
        ))}
      </Stack>
    </Stack>
  );
}

/**
 * Asks before a project is deleted, and what goes with it. Every character and environment the
 * project used is ticked, so everything is deleted unless the user unticks it. An unticked item
 * stays in the library.
 */
export function DeleteProjectModal({ project, onClose, onDeleted }: DeleteProjectModalProps) {
  const projectId = project?.id ?? null;
  const preview = useProjectDeletionPreview(projectId);
  const remove = useDeleteProject(projectId ?? 0);
  // What the user unticked. Everything that can be deleted is ticked until then, so nothing has
  // to be set when the list is loaded.
  const [untickedCharacters, setUntickedCharacters] = useState<Set<number>>(new Set());
  const [untickedEnvironments, setUntickedEnvironments] = useState<Set<number>>(new Set());

  function close() {
    remove.reset();
    setUntickedCharacters(new Set());
    setUntickedEnvironments(new Set());
    onClose();
  }

  function confirm() {
    remove.mutate(
      { characterIds: [...characters], environmentIds: [...environments] },
      {
        onSuccess: () => {
          close();
          onDeleted?.();
        },
      },
    );
  }

  const data = preview.data;
  const blocked = data?.blocked_reason ?? null;
  const characters = ticked(data?.characters ?? [], untickedCharacters);
  const environments = ticked(data?.environments ?? [], untickedEnvironments);
  const sharedCount = data
    ? [...data.characters, ...data.environments].filter(
        (item) =>
          item.other_projects.length > 0 &&
          (characters.has(item.library_id) || environments.has(item.library_id)),
      ).length
    : 0;

  return (
    <Modal
      opened={project !== null}
      onClose={close}
      title={project ? `Delete "${project.name}"?` : ""}
      centered
      size="lg"
    >
      <Stack gap="md">
        {preview.isLoading && <Loader size="sm" />}
        {preview.isError && (
          <Alert color="red" title="Could not load what the project uses">
            {describeError(preview.error)}
          </Alert>
        )}

        {data && (
          <>
            <Text size="sm">
              This deletes the project with its story, every scene, shot and take
              {data.take_count > 0 || data.render_count > 0
                ? ` (${data.take_count} take${data.take_count === 1 ? "" : "s"}, ${data.render_count} render${data.render_count === 1 ? "" : "s"})`
                : ""}{" "}
              and its files. It cannot be undone.
            </Text>

            {blocked && (
              <Alert color="red" title="It cannot be deleted now">
                {blocked}
              </Alert>
            )}

            {data.characters.length + data.environments.length > 0 ? (
              <>
                <Text size="sm">
                  Also delete these characters and environments from the library? Untick any
                  you want to keep.
                </Text>
                <ItemList
                  title="Characters"
                  items={data.characters}
                  selected={characters}
                  onChange={(selected) =>
                    setUntickedCharacters(unticked(data.characters, selected))
                  }
                />
                <ItemList
                  title="Environments"
                  items={data.environments}
                  selected={environments}
                  onChange={(selected) =>
                    setUntickedEnvironments(unticked(data.environments, selected))
                  }
                />
                {sharedCount > 0 && (
                  <Alert color="orange">
                    {sharedCount === 1 ? "One ticked item is" : `${sharedCount} ticked items are`}{" "}
                    also used by other projects. Their scenes and shots keep their files, but
                    read as out of date until the item is created again.
                  </Alert>
                )}
              </>
            ) : (
              <Text size="sm" c="dimmed">
                The project used no characters or environments from the library.
              </Text>
            )}
          </>
        )}

        {remove.isError && (
          <Alert color="red" title="The project was not deleted">
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
            Delete project
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
