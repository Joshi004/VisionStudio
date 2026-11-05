import { useState } from "react";
import {
  Button,
  Checkbox,
  Group,
  MultiSelect,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";

import type { DiscoveryItem } from "../../api/discovery";
import type { SceneDefinition, SceneDefinitionInput } from "../../api/sceneDefinitions";
import { EditorActions } from "./editorParts";

type SceneDefinitionEditorProps = {
  /** The scene's newest definition; the form starts from it. */
  initial: SceneDefinition;
  /** The story's characters and environments: a scene chooses among them. */
  characters: DiscoveryItem[];
  environments: DiscoveryItem[];
  saving: boolean;
  error: unknown;
  onSave: (definition: SceneDefinitionInput) => void;
  onCancel: () => void;
};

/** What the user edits. The scene's id is not here: it is the scene's own. */
type InnerPlace = { environment_id: string; relation: string };
type Draft = SceneDefinitionInput & { off_screen: string[]; inner_places: InnerPlace[] };

/** The most places inside the main place a scene may list (the server checks it as well). */
const MAX_INNER_PLACES = 3;

function toDraft(definition: SceneDefinition): Draft {
  return {
    story_context: { ...definition.story_context },
    environment_id: definition.environment_id,
    environment_state: definition.environment_state,
    inner_places: (definition.inner_places ?? []).map((place) => ({ ...place })),
    time: { ...definition.time },
    characters: [...definition.characters],
    off_screen: [...(definition.off_screen ?? [])],
    character_looks: { ...definition.character_looks },
    mood: { ...definition.mood },
    dramatic_goal: definition.dramatic_goal,
    continuity_start: { ...definition.continuity_start },
    continuity_end: { ...definition.continuity_end },
    continues_previous: definition.continues_previous ?? false,
  };
}

/** The entries of a map for the scene's characters, without the blank ones (blank means none). */
function pickFilled(map: Record<string, string>, characters: string[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const id of characters) {
    const text = (map[id] ?? "").trim();
    if (text !== "") {
      result[id] = text;
    }
  }
  return result;
}

/**
 * One scene's definition as a structured form. The environment and the characters are chosen from
 * the story's lists. A look or a continuity note is kept only for a character in the scene, and
 * a blank one means "nothing to say". The server checks the sizes and the choices, and says which
 * field is wrong.
 */
export function SceneDefinitionEditor({
  initial,
  characters,
  environments,
  saving,
  error,
  onSave,
  onCancel,
}: SceneDefinitionEditorProps) {
  const [draft, setDraft] = useState<Draft>(toDraft(initial));
  const change = (part: Partial<Draft>) => setDraft({ ...draft, ...part });

  // A choice the definition already made stays in the list, even if the story's list lost it,
  // so the form does not hide it; the server then refuses the save and says why.
  const characterOptions = [
    ...characters.map((item) => ({ value: item.id, label: `${item.name} (${item.id})` })),
    ...draft.characters
      .filter((id) => !characters.some((item) => item.id === id))
      .map((id) => ({ value: id, label: id })),
  ];
  const environmentOptions = [
    ...environments.map((item) => ({ value: item.id, label: `${item.name} (${item.id})` })),
    ...(draft.environment_id !== "" && !environments.some((item) => item.id === draft.environment_id)
      ? [{ value: draft.environment_id, label: draft.environment_id }]
      : []),
  ];
  const innerOptions = [
    ...environmentOptions.filter((option) => option.value !== draft.environment_id),
  ];
  const setInnerPlace = (index: number, part: Partial<InnerPlace>) =>
    change({
      inner_places: draft.inner_places.map((place, at) =>
        at === index ? { ...place, ...part } : place,
      ),
    });
  const nameOf = (id: string) => characters.find((item) => item.id === id)?.name ?? id;

  const setCharacterText = (
    field: "character_looks" | "continuity_start" | "continuity_end",
    id: string,
    text: string,
  ) => change({ [field]: { ...draft[field], [id]: text } });

  const save = () =>
    onSave({
      ...draft,
      character_looks: pickFilled(draft.character_looks, draft.characters),
      continuity_start: pickFilled(draft.continuity_start, draft.characters),
      continuity_end: pickFilled(draft.continuity_end, draft.characters),
    });

  return (
    <Stack gap="sm">
      <Title order={5}>Story context</Title>
      <Textarea
        label="Before"
        autosize
        minRows={2}
        value={draft.story_context.before}
        onChange={(event) =>
          change({ story_context: { ...draft.story_context, before: event.currentTarget.value } })
        }
      />
      <Textarea
        label="In this scene"
        autosize
        minRows={2}
        value={draft.story_context.current}
        onChange={(event) =>
          change({ story_context: { ...draft.story_context, current: event.currentTarget.value } })
        }
      />
      <Textarea
        label="After"
        autosize
        minRows={2}
        value={draft.story_context.after}
        onChange={(event) =>
          change({ story_context: { ...draft.story_context, after: event.currentTarget.value } })
        }
      />

      <Title order={5}>Place and time</Title>
      <Select
        label="Environment"
        data={environmentOptions}
        value={draft.environment_id === "" ? null : draft.environment_id}
        allowDeselect={false}
        searchable
        onChange={(value) => change({ environment_id: value ?? "" })}
      />
      <TextInput
        label="Environment state"
        description="How the place looks in this scene."
        value={draft.environment_state}
        onChange={(event) => change({ environment_state: event.currentTarget.value })}
      />
      <Text size="sm" fw={500}>
        Places inside the place
      </Text>
      <Text size="xs" c="dimmed">
        A vehicle, a lift or a booth that some shots of the scene happen inside, such as a car
        parked in the garage. Leave empty when the whole scene happens in the place above.
      </Text>
      {draft.inner_places.map((place, index) => (
        <Group key={index} align="flex-end" wrap="nowrap">
          <Select
            label="Environment"
            data={innerOptions}
            value={place.environment_id === "" ? null : place.environment_id}
            allowDeselect={false}
            searchable
            onChange={(value) => setInnerPlace(index, { environment_id: value ?? "" })}
          />
          <TextInput
            label="How it stands in the place"
            placeholder="parked on garage level P1"
            style={{ flex: 1 }}
            value={place.relation}
            onChange={(event) => setInnerPlace(index, { relation: event.currentTarget.value })}
          />
          <Button
            variant="default"
            onClick={() =>
              change({ inner_places: draft.inner_places.filter((_, at) => at !== index) })
            }
          >
            Remove
          </Button>
        </Group>
      ))}
      {draft.inner_places.length < MAX_INNER_PLACES && (
        <Group>
          <Button
            variant="default"
            size="xs"
            onClick={() =>
              change({
                inner_places: [...draft.inner_places, { environment_id: "", relation: "" }],
              })
            }
          >
            Add a place inside
          </Button>
        </Group>
      )}
      <Checkbox
        label="Continues straight from the previous scene"
        description="The same moment and place, with no jump in time. The first cut of this scene is then checked against the last shot of the scene before it."
        checked={draft.continues_previous ?? false}
        onChange={(event) => change({ continues_previous: event.currentTarget.checked })}
      />
      <TextInput
        label="Time of day"
        value={draft.time.time_of_day}
        onChange={(event) =>
          change({ time: { ...draft.time, time_of_day: event.currentTarget.value } })
        }
      />
      <TextInput
        label="Lighting"
        value={draft.time.lighting_state}
        onChange={(event) =>
          change({ time: { ...draft.time, lighting_state: event.currentTarget.value } })
        }
      />

      <Title order={5}>Characters</Title>
      <MultiSelect
        label="Who is in the scene"
        data={characterOptions}
        value={draft.characters}
        searchable
        onChange={(value) =>
          change({
            characters: value,
            // Someone who leaves the scene cannot be "only heard" in it.
            off_screen: draft.off_screen.filter((id) => value.includes(id)),
          })
        }
      />
      <MultiSelect
        label="Only heard (not seen)"
        description="Characters who are a voice in this scene, such as on the phone or behind a door. They get no place on screen."
        data={characterOptions.filter((option) => draft.characters.includes(option.value))}
        value={draft.off_screen}
        searchable
        onChange={(value) => change({ off_screen: value })}
      />
      {draft.characters.map((id) => (
        <Stack key={id} gap={4}>
          <Text size="sm" fw={500}>
            {nameOf(id)}
          </Text>
          <TextInput
            label="Look in this scene"
            description="Leave blank when the character looks as usual."
            value={draft.character_looks[id] ?? ""}
            onChange={(event) => setCharacterText("character_looks", id, event.currentTarget.value)}
          />
          <TextInput
            label="At the start"
            value={draft.continuity_start[id] ?? ""}
            onChange={(event) =>
              setCharacterText("continuity_start", id, event.currentTarget.value)
            }
          />
          <TextInput
            label="At the end"
            value={draft.continuity_end[id] ?? ""}
            onChange={(event) => setCharacterText("continuity_end", id, event.currentTarget.value)}
          />
        </Stack>
      ))}

      <Title order={5}>Mood and goal</Title>
      <TextInput
        label="Mood at the start"
        value={draft.mood.start}
        onChange={(event) => change({ mood: { ...draft.mood, start: event.currentTarget.value } })}
      />
      <TextInput
        label="Mood in the middle"
        value={draft.mood.middle}
        onChange={(event) => change({ mood: { ...draft.mood, middle: event.currentTarget.value } })}
      />
      <TextInput
        label="Mood at the end"
        value={draft.mood.end}
        onChange={(event) => change({ mood: { ...draft.mood, end: event.currentTarget.value } })}
      />
      <Textarea
        label="Dramatic goal"
        autosize
        minRows={2}
        value={draft.dramatic_goal}
        onChange={(event) => change({ dramatic_goal: event.currentTarget.value })}
      />

      <Text size="xs" c="dimmed">
        Saving adds a new version written by you. The stages after it will say they are out of
        date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the scene definition"
        onSave={save}
        onCancel={onCancel}
      />
    </Stack>
  );
}
