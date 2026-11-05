import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { Link } from "react-router";

import {
  useCharacterOutfits,
  useCreateOutfit,
  useDeleteOutfit,
  useEditOutfit,
  useMakeOutfitDefault,
  useMakeOutfitPictures,
  type Outfit,
} from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { FillFromPhoto } from "./FillFromPhoto";
import { ReferenceStrip } from "./LookPicker";

export const OUTFIT_NAME_MAX_CHARS = 60;
export const OUTFIT_NOTE_MAX_CHARS = 120;
export const OUTFIT_DESCRIPTION_MAX_CHARS = 300;

type OutfitForm = { name: string; note: string; description: string };

const EMPTY_FORM: OutfitForm = { name: "", note: "", description: "" };

function ProjectLinks({ label, projects }: { label: string; projects: Outfit["used_by"] }) {
  return (
    <Group gap={6}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      {projects.length === 0 ? (
        <Text size="xs" c="dimmed">
          none yet
        </Text>
      ) : (
        projects.map((project) => (
          <Anchor key={project.project_id} component={Link} to={`/projects/${project.project_id}`} size="xs">
            {project.project_name}
          </Anchor>
        ))
      )}
    </Group>
  );
}

/** The name, the note and the description of an outfit, to create it or to change it. */
function OutfitFormModal({
  title,
  initial,
  saving,
  error,
  onSave,
  onClose,
}: {
  title: string;
  initial: OutfitForm;
  saving: boolean;
  error: string | null;
  onSave: (form: OutfitForm) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState(initial);
  const ready = form.name.trim() !== "" && form.description.trim() !== "";

  /** Puts what the model read from a photo in the boxes that are still empty. */
  function fillFromPhoto(fields: Record<string, string>) {
    setForm((current) => ({
      name: current.name.trim() === "" ? (fields.name ?? "") : current.name,
      note: current.note.trim() === "" ? (fields.note ?? "") : current.note,
      description:
        current.description.trim() === "" ? (fields.description ?? "") : current.description,
    }));
  }

  return (
    <Modal opened onClose={onClose} title={title} centered>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) {
            onSave(form);
          }
        }}
      >
        <Stack gap="sm">
          {initial.name === "" && <FillFromPhoto mode="outfit" onFilled={fillFromPhoto} />}
          <TextInput
            label="Name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.currentTarget.value })}
            maxLength={OUTFIT_NAME_MAX_CHARS}
            data-autofocus
          />
          <TextInput
            label="Note (optional)"
            description="A few words that help to pick this outfit when a new video is made."
            value={form.note}
            onChange={(event) => setForm({ ...form, note: event.currentTarget.value })}
            maxLength={OUTFIT_NOTE_MAX_CHARS}
          />
          <Textarea
            label="Description"
            description="What is worn, for example: a navy blazer over a white shirt. The pictures are drawn from this text."
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.currentTarget.value })}
            maxLength={OUTFIT_DESCRIPTION_MAX_CHARS}
            autosize
            minRows={3}
            maxRows={6}
          />
          {error !== null && <Alert color="red">{error}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={!ready} loading={saving}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function OutfitCard({
  outfit,
  onEdit,
  onDelete,
  onMakeDefault,
}: {
  outfit: Outfit;
  onEdit: (outfit: Outfit) => void;
  onDelete: (outfit: Outfit) => void;
  onMakeDefault: (outfit: Outfit) => void;
}) {
  const makePictures = useMakeOutfitPictures();
  const busy = outfit.pictures_status === "in_progress";
  const hasPictures = outfit.pictures_status === "ready";

  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Text size="sm" fw={500}>
          {outfit.name}
        </Text>
        {(outfit.is_default || outfit.is_default_now) && (
          <Badge variant="light" size="sm">
            default
          </Badge>
        )}
        {!outfit.is_default && (
          <Badge variant="light" color={hasPictures ? "green" : "gray"} size="sm">
            {busy ? "making pictures" : hasPictures ? "pictures ready" : "no pictures yet"}
          </Badge>
        )}
        {outfit.pictures_out_of_date && (
          <Badge variant="light" color="yellow" size="sm">
            out of date
          </Badge>
        )}
      </Group>
      {outfit.note !== null && outfit.note !== "" && <Text size="xs">{outfit.note}</Text>}
      <Text size="xs" c="dimmed">
        {outfit.description}
      </Text>
      {outfit.look !== null && hasPictures && <ReferenceStrip look={outfit.look} />}
      {!outfit.is_default && (
        <>
          <ProjectLinks label="Made for:" projects={outfit.made_for === null ? [] : [outfit.made_for]} />
          <ProjectLinks label="Used by:" projects={outfit.used_by} />
        </>
      )}
      {outfit.is_default && (
        <Text size="xs" c="dimmed">
          To remove it, make another outfit the default; this one is then kept as a saved outfit
          you can delete.
        </Text>
      )}
      {outfit.blocked_reason !== null && !hasPictures && !busy && !outfit.is_default && (
        <Text size="xs" c="dimmed">
          {outfit.blocked_reason}
        </Text>
      )}
      {makePictures.isError && <Alert color="red" p="xs">{describeError(makePictures.error)}</Alert>}
      {!outfit.is_default && outfit.id !== null && (
        <Group gap="xs">
          <Button size="compact-xs" variant="default" onClick={() => onEdit(outfit)}>
            Edit
          </Button>
          <Button
            size="compact-xs"
            variant="light"
            loading={makePictures.isPending}
            disabled={busy || (outfit.blocked_reason !== null && !hasPictures)}
            onClick={() => makePictures.mutate(outfit.id as number)}
          >
            {hasPictures ? "Remake pictures" : "Make pictures"}
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            disabled={outfit.is_default_now || !hasPictures || outfit.pictures_out_of_date || busy}
            title={
              outfit.is_default_now
                ? "This outfit is the default already."
                : !hasPictures
                  ? "Make its pictures first."
                  : outfit.pictures_out_of_date
                    ? "Its pictures are out of date. Make them again first."
                    : undefined
            }
            onClick={() => onMakeDefault(outfit)}
          >
            Make default
          </Button>
          <Button size="compact-xs" variant="subtle" color="red" onClick={() => onDelete(outfit)}>
            Delete
          </Button>
        </Group>
      )}
    </Stack>
  );
}

/**
 * The outfits of one character: the default one and every saved one. Each saved outfit has a
 * name, a short note for picking it, and the description its pictures are drawn from. Deleting
 * one never changes a project that already uses it.
 */
export function Outfits({ characterId }: { characterId: number }) {
  const outfits = useCharacterOutfits(characterId);
  const create = useCreateOutfit();
  const edit = useEditOutfit();
  const remove = useDeleteOutfit();
  const makeDefault = useMakeOutfitDefault();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Outfit | null>(null);
  const [deleting, setDeleting] = useState<Outfit | null>(null);
  const [defaulting, setDefaulting] = useState<Outfit | null>(null);

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text size="sm" fw={600}>
          Outfits
        </Text>
        <Button
          size="compact-xs"
          variant="light"
          onClick={() => {
            create.reset();
            setCreating(true);
          }}
        >
          New outfit
        </Button>
      </Group>
      {outfits.isLoading && <Loader size="xs" />}
      {outfits.isError && (
        <Alert color="red" p="xs" title="Could not load the outfits">
          {describeError(outfits.error)}
        </Alert>
      )}
      {outfits.data?.map((outfit) => (
        <OutfitCard
          key={outfit.id ?? "default"}
          outfit={outfit}
          onEdit={(value) => {
            edit.reset();
            setEditing(value);
          }}
          onDelete={(value) => {
            remove.reset();
            setDeleting(value);
          }}
          onMakeDefault={(value) => {
            makeDefault.reset();
            setDefaulting(value);
          }}
        />
      ))}

      {creating && (
        <OutfitFormModal
          title="New outfit"
          initial={EMPTY_FORM}
          saving={create.isPending}
          error={create.isError ? describeError(create.error) : null}
          onClose={() => setCreating(false)}
          onSave={(form) =>
            create.mutate(
              {
                characterId,
                body: {
                  name: form.name,
                  note: form.note.trim() === "" ? null : form.note,
                  description: form.description,
                },
              },
              { onSuccess: () => setCreating(false) },
            )
          }
        />
      )}

      {editing !== null && editing.id !== null && (
        <OutfitFormModal
          title={`Edit ${editing.name}`}
          initial={{
            name: editing.name,
            note: editing.note ?? "",
            description: editing.description,
          }}
          saving={edit.isPending}
          error={edit.isError ? describeError(edit.error) : null}
          onClose={() => setEditing(null)}
          onSave={(form) =>
            edit.mutate(
              {
                outfitId: editing.id as number,
                body: {
                  name: form.name,
                  // An emptied note clears it.
                  note: form.note.trim() === "" ? "" : form.note,
                  description: form.description,
                },
              },
              { onSuccess: () => setEditing(null) },
            )
          }
        />
      )}

      <Modal
        opened={defaulting !== null}
        onClose={() => setDefaulting(null)}
        title={`Make ${defaulting?.name ?? "outfit"} the default?`}
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            This outfit&apos;s pictures and text become the character&apos;s default. New takes and
            new projects use it; existing projects keep the version they pinned. The current
            default is kept as a saved outfit.
          </Text>
          {makeDefault.isError && <Alert color="red">{describeError(makeDefault.error)}</Alert>}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setDefaulting(null)}
              disabled={makeDefault.isPending}
            >
              Cancel
            </Button>
            <Button
              loading={makeDefault.isPending}
              onClick={() =>
                makeDefault.mutate(defaulting?.id as number, {
                  onSuccess: () => setDefaulting(null),
                })
              }
            >
              Make default
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={deleting !== null}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.name ?? "outfit"}?`}
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Existing projects keep this outfit; it won&apos;t be offered for new ones.
          </Text>
          {remove.isError && <Alert color="red">{describeError(remove.error)}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleting(null)} disabled={remove.isPending}>
              Cancel
            </Button>
            <Button
              color="red"
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(deleting?.id as number, { onSuccess: () => setDeleting(null) })
              }
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
