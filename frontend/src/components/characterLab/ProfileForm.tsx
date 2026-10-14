import { useState } from "react";
import {
  Alert,
  Autocomplete,
  Button,
  Group,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import {
  useCharacterOptions,
  useCreateCharacter,
  useEditCharacter,
  type LibraryCharacter,
} from "../../api/characterLab";
import { describeError } from "../../api/errors";
import {
  DEFAULT_PROFILE,
  LIMITS,
  profileFromCharacter,
  profileProblem,
  toCharacterIn,
  type EraKind,
  type ProfileFormState,
} from "./characterLabView";

type ProfileFormProps = {
  /** The character to edit, or null to make a new one. */
  character: LibraryCharacter | null;
  /** Called with the saved character. `created` is true for a new one. */
  onSaved: (character: LibraryCharacter, created: boolean) => void;
};

function counter(text: string, limit: number): string {
  return `${text.length.toLocaleString()} of ${limit.toLocaleString()} characters.`;
}

/**
 * The profile step: who the character is. Only the name, the species and the appearance are
 * required. The appearance is what every picture is drawn from, so it describes the body and
 * the features that never change, not the clothes (the outfit has its own box).
 */
export function ProfileForm({ character, onSaved }: ProfileFormProps) {
  const [form, setForm] = useState<ProfileFormState>(() =>
    character === null ? DEFAULT_PROFILE : profileFromCharacter(character),
  );
  const [saved, setSaved] = useState(false);
  const options = useCharacterOptions();
  const create = useCreateCharacter();
  const edit = useEditCharacter();
  const saving = create.isPending || edit.isPending;
  const failure = create.isError ? create.error : edit.isError ? edit.error : null;
  const problem = profileProblem(form);

  function update(changes: Partial<ProfileFormState>) {
    setSaved(false);
    setForm((current) => ({ ...current, ...changes }));
  }

  function save() {
    const body = toCharacterIn(form);
    if (character === null) {
      create.mutate(body, { onSuccess: (made) => onSaved(made, true) });
    } else {
      edit.mutate(
        { characterId: character.id, body },
        {
          onSuccess: (changed) => {
            setSaved(true);
            onSaved(changed, false);
          },
        },
      );
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (problem === null && !saving) {
          save();
        }
      }}
    >
      <Stack gap="md">
        <TextInput
          label="Name"
          required
          value={form.name}
          onChange={(event) => update({ name: event.currentTarget.value })}
          description={counter(form.name, LIMITS.name)}
        />

        <Group grow align="flex-start">
          <Autocomplete
            label="Species"
            required
            description="Pick one or type your own: human, robot, fish, dog..."
            data={options.data?.species ?? []}
            value={form.species}
            onChange={(species) => update({ species })}
          />
          <Autocomplete
            label="Gender"
            description="Optional."
            data={options.data?.genders ?? []}
            value={form.gender}
            onChange={(gender) => update({ gender })}
          />
          <TextInput
            label="Age"
            description="Years. Optional."
            inputMode="numeric"
            value={form.age}
            onChange={(event) => update({ age: event.currentTarget.value })}
          />
        </Group>

        <Stack gap={4}>
          <Text size="sm" fw={500}>
            When does it live?
          </Text>
          <SegmentedControl
            value={form.eraKind}
            onChange={(value) => update({ eraKind: value as EraKind })}
            data={[
              { value: "present", label: "Present" },
              { value: "past", label: "Past" },
              { value: "future", label: "Future" },
            ]}
          />
        </Stack>
        <Group grow align="flex-start">
          {form.eraKind !== "present" && (
            <TextInput
              label={`Years in the ${form.eraKind}`}
              required
              inputMode="numeric"
              description={`From 1 to ${LIMITS.eraYearsMax.toLocaleString()}.`}
              value={form.eraYears}
              onChange={(event) => update({ eraYears: event.currentTarget.value })}
            />
          )}
          <TextInput
            label="Setting"
            description="Optional. For example: Victorian London, Edo-period Japan."
            value={form.eraSetting}
            onChange={(event) => update({ eraSetting: event.currentTarget.value })}
          />
        </Group>

        <Textarea
          label="Appearance"
          required
          description={`The body and the features that never change: build, face, skin or fur, hair. ${counter(form.appearance, LIMITS.appearance)}`}
          value={form.appearance}
          onChange={(event) => update({ appearance: event.currentTarget.value })}
          autosize
          minRows={3}
        />
        <Textarea
          label="Outfit"
          description={`Optional. What it wears by default. ${counter(form.outfit, LIMITS.outfit)}`}
          value={form.outfit}
          onChange={(event) => update({ outfit: event.currentTarget.value })}
          autosize
          minRows={2}
        />
        <Textarea
          label="Personality"
          description={`Optional. How it behaves. It steers the voice's delivery. ${counter(form.personality, LIMITS.personality)}`}
          value={form.personality}
          onChange={(event) => update({ personality: event.currentTarget.value })}
          autosize
          minRows={2}
        />
        <Textarea
          label="Notes"
          description={`Optional. Anything else every picture and clip should keep: its height, a feature that never changes, how it moves. ${counter(form.notes, LIMITS.notes)}`}
          value={form.notes}
          onChange={(event) => update({ notes: event.currentTarget.value })}
          autosize
          minRows={2}
        />
        <Switch
          label="Has a visible mouth"
          description="Lip sync only works on a mouth that can be seen. Turn this off for a character whose mouth is never visible."
          checked={form.hasVisibleMouth}
          onChange={(event) => update({ hasVisibleMouth: event.currentTarget.checked })}
        />

        {character !== null && (
          <Text size="xs" c="dimmed">
            Changing the appearance, outfit or notes does not change the pictures already made.
            Make a new look to use them.
          </Text>
        )}

        <Stack gap={6} align="flex-start">
          <Button type="submit" loading={saving} disabled={problem !== null}>
            {character === null ? "Save and make a look" : "Save changes"}
          </Button>
          {problem !== null && form.name.trim() !== "" && (
            <Alert color="yellow" p="xs">
              {problem}
            </Alert>
          )}
          {failure !== null && (
            <Alert color="red" p="xs" title="The character was not saved">
              {describeError(failure)}
            </Alert>
          )}
          {saved && (
            <Alert color="green" p="xs">
              Saved.
            </Alert>
          )}
        </Stack>
      </Stack>
    </form>
  );
}
