import type { Dispatch, SetStateAction } from "react";
import { Button, Group, Paper, Select, Stack, Text, TextInput, Textarea } from "@mantine/core";

import { useLibraryCharacters, type LibraryCharacter } from "../../api/characterLab";
import { useVoices } from "../../api/voiceLab";
import { ReferenceTray } from "../imageLab/ReferenceTray";
import { AudioReferencePicker } from "./AudioReferencePicker";
import { FirstFramePicker } from "./FirstFramePicker";
import {
  AMBIENCE_MAX_CHARS,
  EMPTY_CHARACTER,
  H3_MAX_REFERENCES,
  lookPicture,
  slotFromCharacter,
  withCharacter,
  type CharacterSlot,
  type VideoLabFormState,
} from "./videoLabView";

type ReferenceComposerProps = {
  state: VideoLabFormState;
  /** Takes a function of the current form, so a change made while an upload runs does not undo
   * what was typed meanwhile. */
  onChange: Dispatch<SetStateAction<VideoLabFormState>>;
};

type CharacterSlotEditorProps = {
  index: number;
  title: string;
  slot: CharacterSlot;
  /** Characters of the library that have a picture to use. */
  library: LibraryCharacter[];
  onFromLibrary: (character: LibraryCharacter) => void;
  onChange: (changes: Partial<CharacterSlot>) => void;
};

/** One character: a picture (from the library or any picture), a name, a look and a voice. */
function CharacterSlotEditor({
  index,
  title,
  slot,
  library,
  onFromLibrary,
  onChange,
}: CharacterSlotEditorProps) {
  const isEmpty = slot.picture === null && slot.voice === null && slot.name === "";
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text fw={600}>{title}</Text>
          <Group gap="xs">
            {library.length > 0 && (
              <Select
                aria-label={`${title} from the library`}
                placeholder="From the library"
                data={library.map((character) => ({
                  value: String(character.id),
                  label: character.name,
                }))}
                value={null}
                onChange={(value) => {
                  const picked = library.find((character) => String(character.id) === value);
                  if (picked !== undefined) {
                    onFromLibrary(picked);
                  }
                }}
                searchable
                nothingFoundMessage="No character."
                w={200}
              />
            )}
            <Button
              size="compact-sm"
              variant="subtle"
              color="red"
              disabled={isEmpty}
              onClick={() => onChange(EMPTY_CHARACTER)}
            >
              Clear
            </Button>
          </Group>
        </Group>

        <FirstFramePicker
          title="Picture"
          value={slot.picture}
          onChange={(picture) => onChange({ picture })}
          emptyText={
            index === 0
              ? "No picture. A character from the library fills this in, or upload one."
              : "No second character."
          }
          hint="H3 keeps this person's face and clothes. A full-body picture on a plain background works best."
        />
        <Group align="flex-start" grow>
          <TextInput
            label="Name"
            description="What the prompt calls them."
            placeholder="Mara"
            value={slot.name}
            onChange={(event) => onChange({ name: event.currentTarget.value })}
            maxLength={80}
          />
          <Textarea
            label="Looks and clothes"
            description="Goes into subject_definitions."
            value={slot.description}
            onChange={(event) => onChange({ description: event.currentTarget.value })}
            autosize
            minRows={2}
            maxLength={500}
          />
        </Group>
        <AudioReferencePicker
          title="Voice (optional)"
          value={slot.voice}
          onChange={(voice) => onChange({ voice })}
          hint="Without a voice, H3 makes one up. With one, it follows that timbre and delivery but makes its own sound: the recording itself is not in the clip."
        />
      </Stack>
    </Paper>
  );
}

/**
 * The cast of a MiniMax H3 reference clip: up to two characters (each with an optional voice),
 * a scene, the ambience, and any other pictures. The prompt skeleton is made from this.
 */
export function ReferenceComposer({ state, onChange }: ReferenceComposerProps) {
  const characters = useLibraryCharacters(false);
  const voices = useVoices();
  const library = (characters.data?.pages.flatMap((page) => page.characters) ?? []).filter(
    (character) => lookPicture(character) !== null,
  );

  const slotPictures =
    state.characters.filter((slot) => slot.picture !== null).length +
    (state.scene.picture === null ? 0 : 1);
  const otherMax = Math.max(0, H3_MAX_REFERENCES - slotPictures);

  function fromLibrary(index: number, character: LibraryCharacter) {
    const slot = slotFromCharacter(character, voices.data ?? []);
    if (slot !== null) {
      onChange((current) => withCharacter(current, index, slot));
    }
  }

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Up to {H3_MAX_REFERENCES} pictures in all. Try one character, or two together, in a
        scene. Every part is optional but at least one picture is needed.
      </Text>

      {state.characters.map((slot, index) => (
        <CharacterSlotEditor
          key={index}
          index={index}
          title={index === 0 ? "Character 1" : "Character 2 (optional)"}
          slot={slot}
          library={library}
          onFromLibrary={(character) => fromLibrary(index, character)}
          onChange={(changes) => onChange((current) => withCharacter(current, index, changes))}
        />
      ))}

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Text fw={600}>Scene (optional)</Text>
          <FirstFramePicker
            title="Scene picture"
            value={state.scene.picture}
            onChange={(picture) =>
              onChange((current) => ({ ...current, scene: { ...current.scene, picture } }))
            }
            emptyText="No scene picture: describe the place in the prompt."
            hint="A picture of the place. H3 keeps its layout, light and mood as the setting."
          />
          <Textarea
            label="Scene description"
            description="Where it happens and what the place looks like."
            value={state.scene.description}
            onChange={(event) => {
              const description = event.currentTarget.value;
              onChange((current) => ({ ...current, scene: { ...current.scene, description } }));
            }}
            autosize
            minRows={2}
            maxLength={500}
          />
        </Stack>
      </Paper>

      <Textarea
        label="Ambience (optional)"
        description="The sounds of the place, for overall_soundscape: rain on a window, a busy street, a quiet room. No speech."
        value={state.ambience}
        onChange={(event) => {
          const ambience = event.currentTarget.value;
          onChange((current) => ({ ...current, ambience }));
        }}
        autosize
        minRows={2}
        maxLength={AMBIENCE_MAX_CHARS}
      />

      <ReferenceTray
        items={state.references}
        onChange={(updater) =>
          onChange((current) => ({ ...current, references: updater(current.references) }))
        }
        max={otherMax}
        title="Other pictures"
        itemName={(position) => `other ${position}`}
        footnote="An object, a pet, another place. They come after the characters and the scene in the prompt's <Picture n> numbers."
      />
    </Stack>
  );
}
