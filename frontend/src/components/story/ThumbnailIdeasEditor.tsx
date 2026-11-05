import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Button,
  Checkbox,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import type {
  ThumbnailCastOption,
  ThumbnailConcept,
  ThumbnailConceptInput,
  ThumbnailTextArea,
} from "../../api/thumbnails";

/** The most people the model may put on one thumbnail. */
const MAX_PEOPLE = 2;
/** The longest headline the backend accepts. */
const MAX_HEADLINE_CHARS = 40;

const TEXT_AREA_LABELS: Record<ThumbnailTextArea, string> = {
  left: "Left",
  right: "Right",
  top: "Top",
  bottom: "Bottom",
  top_left: "Top left",
  top_right: "Top right",
  bottom_left: "Bottom left",
  bottom_right: "Bottom right",
};

const TEXT_AREA_OPTIONS = (
  Object.keys(TEXT_AREA_LABELS) as ThumbnailTextArea[]
).map((value) => ({
  value,
  label: TEXT_AREA_LABELS[value],
}));

type ThumbnailIdeasEditorProps = {
  concepts: ThumbnailConcept[];
  cast: ThumbnailCastOption[];
  /** True while the ideas or a picture are being made: nothing can be changed or started. */
  busy: boolean;
  saving: boolean;
  saveError: unknown;
  making: boolean;
  makeError: unknown;
  onSave: (concepts: ThumbnailConceptInput[]) => void;
  onMake: (indexes: number[]) => void;
};

/**
 * The four ideas, one card each. The owner can change the headline, where it goes and who is on
 * the picture. Saving adds a version written by the owner. Ticked ideas are the ones that
 * "Make pictures" turns into pictures; it only works on saved ideas.
 */
export function ThumbnailIdeasEditor({
  concepts,
  cast,
  busy,
  saving,
  saveError,
  making,
  makeError,
  onSave,
  onMake,
}: ThumbnailIdeasEditorProps) {
  const [draft, setDraft] = useState<ThumbnailConceptInput[]>(concepts);
  const [ticked, setTicked] = useState<number[]>(() =>
    concepts.map((_, index) => index),
  );
  const changed = JSON.stringify(draft) !== JSON.stringify(concepts);

  const change = (index: number, patch: Partial<ThumbnailConceptInput>) =>
    setDraft((current) =>
      current.map((concept, at) =>
        at === index ? { ...concept, ...patch } : concept,
      ),
    );

  const toggle = (index: number, on: boolean) =>
    setTicked((current) =>
      on
        ? [...current, index].sort((a, b) => a - b)
        : current.filter((at) => at !== index),
    );

  return (
    <Stack gap="sm">
      {draft.map((concept, index) => (
        <Paper key={index} withBorder p="md" radius="md">
          <Stack gap="xs">
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Checkbox
                label={`${index + 1}. ${concept.label}`}
                fw={600}
                checked={ticked.includes(index)}
                onChange={(event) => toggle(index, event.currentTarget.checked)}
              />
            </Group>
            <Text size="sm">{concept.idea}</Text>
            <Text size="xs" c="dimmed">
              Picture: {concept.composition} Background: {concept.background}{" "}
              Mood: {concept.mood}
            </Text>
            <Group align="flex-end" grow>
              <TextInput
                label="Headline"
                description="Up to 6 words. Drawn on the picture by the app, not by the image model."
                maxLength={MAX_HEADLINE_CHARS}
                value={concept.headline}
                onChange={(event) =>
                  change(index, { headline: event.currentTarget.value })
                }
              />
              <Select
                label="Where the headline goes"
                allowDeselect={false}
                data={TEXT_AREA_OPTIONS}
                value={concept.text_area}
                onChange={(value) =>
                  value &&
                  change(index, { text_area: value as ThumbnailTextArea })
                }
              />
            </Group>
            <PeopleEditor
              people={concept.people}
              cast={cast}
              reason={concept.people_reason}
              onChange={(people) => change(index, { people })}
            />
          </Stack>
        </Paper>
      ))}

      {saveError != null && (
        <Alert color="red" title="Could not save the ideas">
          {describeError(saveError)}
        </Alert>
      )}
      {makeError != null && (
        <Alert color="red" title="Could not start the pictures">
          {describeError(makeError)}
        </Alert>
      )}
      <Group justify="space-between">
        <Group gap="xs">
          <Button
            variant="default"
            onClick={() => onSave(draft)}
            loading={saving}
            disabled={!changed || busy}
          >
            Save as my version
          </Button>
          {changed && (
            <Button
              variant="subtle"
              color="gray"
              onClick={() => setDraft(concepts)}
            >
              Undo changes
            </Button>
          )}
        </Group>
        <Group gap="xs">
          {changed && (
            <Text size="sm" c="dimmed">
              Save your changes first.
            </Text>
          )}
          <Button
            onClick={() => onMake(ticked)}
            loading={making}
            disabled={changed || busy || ticked.length === 0}
          >
            Make pictures ({ticked.length})
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}

type PeopleEditorProps = {
  people: ThumbnailConceptInput["people"];
  cast: ThumbnailCastOption[];
  reason: string;
  onChange: (people: ThumbnailConceptInput["people"]) => void;
};

/** Who is on the picture: none, or up to two people from the cast, each with a look. */
function PeopleEditor({ people, cast, reason, onChange }: PeopleEditorProps) {
  const looksOf = (id: string) =>
    cast.find((option) => option.id === id)?.looks ?? [];

  const update = (
    at: number,
    patch: Partial<ThumbnailConceptInput["people"][number]>,
  ) =>
    onChange(
      people.map((person, index) =>
        index === at ? { ...person, ...patch } : person,
      ),
    );

  const add = () => {
    const first = cast[0];
    if (!first || !first.looks[0]) return;
    onChange([
      ...people,
      { id: first.id, look: first.looks[0].slug, expression: "", pose: "" },
    ]);
  };

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text size="sm" fw={500}>
          {people.length === 0
            ? "No people on this picture"
            : "People on this picture"}
        </Text>
        <Button
          variant="subtle"
          size="compact-sm"
          onClick={add}
          disabled={people.length >= MAX_PEOPLE || cast.length === 0}
        >
          Add a person
        </Button>
      </Group>
      {reason && (
        <Text size="xs" c="dimmed">
          {reason}
        </Text>
      )}
      {people.map((person, at) => (
        <Group key={at} align="flex-end" wrap="nowrap">
          <Select
            label="Person"
            allowDeselect={false}
            data={cast.map((option) => ({
              value: option.id,
              label: option.name,
            }))}
            value={person.id}
            onChange={(value) => {
              const first = value ? looksOf(value)[0] : undefined;
              if (value && first) update(at, { id: value, look: first.slug });
            }}
          />
          <Select
            label="Look"
            allowDeselect={false}
            data={looksOf(person.id).map((look) => ({
              value: look.slug,
              label: look.slug,
            }))}
            value={person.look}
            onChange={(value) => value && update(at, { look: value })}
          />
          <TextInput
            label="Expression"
            value={person.expression}
            onChange={(event) =>
              update(at, { expression: event.currentTarget.value })
            }
          />
          <TextInput
            label="Pose"
            value={person.pose}
            onChange={(event) =>
              update(at, { pose: event.currentTarget.value })
            }
          />
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label="Remove this person"
            onClick={() => onChange(people.filter((_, index) => index !== at))}
          >
            ×
          </ActionIcon>
        </Group>
      ))}
    </Stack>
  );
}
