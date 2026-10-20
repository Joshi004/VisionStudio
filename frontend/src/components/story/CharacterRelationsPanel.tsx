import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import {
  useCharacterRelations,
  useFindRelations,
  useSaveRelations,
  type RelationInput,
} from "../../api/characterRelations";
import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";

type CharacterRelationsPanelProps = {
  projectId: number;
};

type Kind = RelationInput["kind"];

/** What `character` is to `of`, in words. `child` and `grandchild` are only for editing. */
const KIND_TEXT: Record<Kind, string> = {
  younger_self: "is the younger self of",
  older_self: "is the older self of",
  twin: "is the identical twin of",
  parent: "is a parent of",
  child: "is a child of",
  sibling: "is a brother or sister of",
  grandparent: "is a grandparent of",
  grandchild: "is a grandchild of",
};

const KIND_OPTIONS = (Object.keys(KIND_TEXT) as Kind[]).map((kind) => ({
  value: kind,
  label: KIND_TEXT[kind],
}));

/** The kinds that make two characters one face: the images stage edits the base's picture. */
const SAME_FACE: readonly string[] = ["younger_self", "older_self", "twin"];

/** A relation being edited: a field is null until the user picks it. */
type Draft = { character: string | null; kind: Kind | null; of: string | null };

/**
 * The Character relations stage: one model call reads the story and the characters and lists
 * how they are related (the same person at another age, twins, parents, brothers and sisters).
 * The list can be edited by hand; an edit is saved as a new version. The definitions read the
 * relations, and the images stage uses them: the same person at another age is drawn from the
 * main version's picture, so both have one face, and a relative is drawn with the family's
 * skin tone, eyes and face shape.
 */
export function CharacterRelationsPanel({ projectId }: CharacterRelationsPanelProps) {
  const { data, isLoading, isError, error } = useCharacterRelations(projectId);
  const find = useFindRelations(projectId);
  const save = useSaveRelations(projectId);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [confirming, setConfirming] = useState(false);

  const job = data?.job ?? null;
  const active = isJobActive(job);
  const characters = data?.characters ?? [];
  const nameOf = (id: string) => characters.find((item) => item.id === id)?.name ?? id;
  const options = characters.map((item) => ({ value: item.id, label: item.name }));
  const editing = drafts !== null;

  const startFind = () => {
    if (data?.needs_confirmation) {
      setConfirming(true);
    } else {
      find.mutate({ confirmReplaceManual: false });
    }
  };

  const startEdit = () => {
    save.reset();
    setDrafts((data?.relations ?? []).map((item) => ({ ...item })));
  };

  const changeDraft = (index: number, change: Partial<Draft>) => {
    setDrafts((current) =>
      current === null
        ? current
        : current.map((draft, position) => (position === index ? { ...draft, ...change } : draft)),
    );
  };

  const complete: RelationInput[] = (drafts ?? []).flatMap((draft) =>
    draft.character !== null && draft.kind !== null && draft.of !== null
      ? [{ character: draft.character, kind: draft.kind, of: draft.of }]
      : [],
  );
  const allComplete = drafts !== null && complete.length === drafts.length;

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Character relations</Title>
              <Text size="sm" c="dimmed">
                How the characters are related: the same person at another age, twins, parents,
                brothers and sisters. Two versions of one person are drawn with the same face;
                relatives are drawn with a family likeness.
              </Text>
            </Stack>
            <Group gap="sm">
              <Button
                variant="default"
                onClick={startEdit}
                disabled={editing || isLoading || isError || characters.length < 2 || active}
              >
                Edit
              </Button>
              <Button
                onClick={startFind}
                loading={find.isPending || active}
                disabled={isLoading || isError || editing || !(data?.can_run ?? false)}
              >
                {data?.latest ? "Find again" : "Find relations"}
              </Button>
            </Group>
          </Group>

          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the relations">
              {describeError(error)}
            </Alert>
          )}
          {find.isError && (
            <Alert color="red" title="Could not start the relations search">
              {describeError(find.error)}
            </Alert>
          )}
          {data && !data.can_run && !active && data.blocked_reason !== null && (
            <Text size="sm" c="dimmed">
              {data.blocked_reason}
            </Text>
          )}
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          {job?.status === "failed" && (
            <Alert color="red" title="The last search failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {data && data.reasons.length > 0 && !editing && (
            <Alert color="yellow" title="Out of date">
              <Stack gap={2}>
                {data.reasons.map((text) => (
                  <Text key={text} size="sm">
                    {text}
                  </Text>
                ))}
                <Text size="sm">Find the relations again, or edit them.</Text>
              </Stack>
            </Alert>
          )}

          {editing && drafts !== null && (
            <Stack gap="xs">
              {drafts.map((draft, index) => (
                <Group key={index} gap="xs" align="flex-end" wrap="nowrap">
                  <Select
                    aria-label="Character"
                    placeholder="Character"
                    data={options}
                    value={draft.character}
                    onChange={(value) => changeDraft(index, { character: value })}
                    style={{ flex: 1 }}
                  />
                  <Select
                    aria-label="Relation"
                    placeholder="Relation"
                    data={KIND_OPTIONS}
                    value={draft.kind}
                    onChange={(value) => changeDraft(index, { kind: value as Kind | null })}
                    style={{ flex: 1 }}
                  />
                  <Select
                    aria-label="Of"
                    placeholder="Of"
                    data={options}
                    value={draft.of}
                    onChange={(value) => changeDraft(index, { of: value })}
                    style={{ flex: 1 }}
                  />
                  <Button
                    variant="default"
                    color="red"
                    aria-label="Remove this relation"
                    onClick={() => setDrafts(drafts.filter((_, position) => position !== index))}
                  >
                    Remove
                  </Button>
                </Group>
              ))}
              {drafts.length === 0 && (
                <Text size="sm" c="dimmed">
                  No relations. Add one, or save to say the characters are not related.
                </Text>
              )}
              {save.isError && (
                <Alert color="red" title="Could not save the relations">
                  {describeError(save.error)}
                </Alert>
              )}
              <Group>
                <Button
                  variant="default"
                  onClick={() =>
                    setDrafts([...drafts, { character: null, kind: null, of: null }])
                  }
                >
                  Add a relation
                </Button>
                <Button
                  loading={save.isPending}
                  disabled={!allComplete}
                  onClick={() => save.mutate(complete, { onSuccess: () => setDrafts(null) })}
                >
                  Save
                </Button>
                <Button variant="default" onClick={() => setDrafts(null)} disabled={save.isPending}>
                  Cancel
                </Button>
              </Group>
            </Stack>
          )}
        </Stack>
      </Paper>

      {data?.latest && !editing && (
        <ArtifactViewer
          title="Relations"
          version={data.latest.version}
          source={data.latest.source}
          jobId={data.latest.job_id}
          createdAt={data.latest.created_at}
        >
          <Stack gap="xs">
            {data.relations.length === 0 && (
              <Text size="sm" c="dimmed">
                The characters are not related in a way that changes how they look.
              </Text>
            )}
            {data.relations.map((item) => (
              <Group key={`${item.character}-${item.of}`} gap="xs">
                <Text size="sm" fw={500}>
                  {nameOf(item.character)}
                </Text>
                <Text size="sm" c="dimmed">
                  {KIND_TEXT[item.kind]}
                </Text>
                <Text size="sm" fw={500}>
                  {nameOf(item.of)}
                </Text>
                <Badge
                  variant="light"
                  color={SAME_FACE.includes(item.kind) ? "grape" : "teal"}
                  title={
                    SAME_FACE.includes(item.kind)
                      ? "Drawn by editing the main version's picture, so both have the same face"
                      : "Drawn with a family likeness: the relative's skin tone, eyes and face shape"
                  }
                >
                  {SAME_FACE.includes(item.kind) ? "Same face" : "Family"}
                </Badge>
              </Group>
            ))}
            {data.dropped.map((item) => (
              <Text key={`${item.character}-${item.of}`} size="sm" c="dimmed">
                {item.character} {KIND_TEXT[item.kind]} {item.of} (a character that is no longer
                in the list; ignored)
              </Text>
            ))}
          </Stack>
        </ArtifactViewer>
      )}

      <Modal
        opened={confirming}
        onClose={() => setConfirming(false)}
        title="Find the relations again?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            The newest relations were written by you. Finding them again adds a new version from
            the model on top. Your version stays in the list of versions.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              color="red"
              onClick={() => {
                find.mutate({ confirmReplaceManual: true });
                setConfirming(false);
              }}
            >
              Find again
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
