import { useState } from "react";
import { Alert, Button, Group, Modal, Select, Stack, Text, TextInput, Textarea } from "@mantine/core";

import { useCreateCharacter, useUpdateCharacter, type Character } from "../../api/characters";
import { describeError } from "../../api/errors";
import { useVoices } from "../../api/voiceLab";
import { Thumb } from "../imageLab/ReferenceTray";
import type { ReferenceItem } from "../imageLab/labView";
import { CHARACTER_NOTE_MAX_CHARS, VOICE_INSTRUCTION_MAX_CHARS } from "./talkLabView";

const NAME_MAX_CHARS = 80;

type SaveCharacterModalProps = {
  opened: boolean;
  onClose: () => void;
  /** The picture of a new character. Not used when `character` is given: its picture stays. */
  image: ReferenceItem | null;
  /** Change this character instead of saving a new one. */
  character?: Character;
  /** What a new character starts with, for example the take it is made from. */
  defaults?: {
    name?: string;
    description?: string;
    voiceId?: number | null;
    voiceInstruction?: string | null;
  };
};

/**
 * Saves a character of the cast: a name, the picture that pins how it looks, a description (the
 * language model that writes the prompts cannot see the picture, so this is all it knows of the
 * character), and an optional default voice. The state starts from the props when the modal is
 * created, so give it a `key` that changes with what it is for.
 */
export function SaveCharacterModal({
  opened,
  onClose,
  image,
  character,
  defaults,
}: SaveCharacterModalProps) {
  const create = useCreateCharacter();
  const update = useUpdateCharacter();
  const voices = useVoices();
  const [name, setName] = useState(character?.name ?? defaults?.name ?? "");
  const [description, setDescription] = useState(
    character?.description ?? defaults?.description ?? "",
  );
  const [voiceId, setVoiceId] = useState<string | null>(
    character !== undefined
      ? character.voice === null
        ? null
        : String(character.voice.id)
      : defaults?.voiceId != null
        ? String(defaults.voiceId)
        : null,
  );
  const [voiceInstruction, setVoiceInstruction] = useState(
    character?.voice_instruction ?? defaults?.voiceInstruction ?? "",
  );

  const picture = character !== undefined ? character.image : image;
  const pictureUrl = picture?.url ?? null;
  const problem =
    name.trim() === ""
      ? "Give the character a name."
      : character === undefined && image === null
        ? "A character needs a picture."
        : null;
  const mutation = character !== undefined ? update : create;

  function save() {
    const fields = {
      name: name.trim(),
      description: description.trim(),
      voice_id: voiceId === null ? null : Number(voiceId),
      voice_instruction: voiceInstruction.trim() === "" ? null : voiceInstruction.trim(),
    };
    if (character !== undefined) {
      update.mutate({ characterId: character.id, body: fields }, { onSuccess: onClose });
    } else if (image !== null) {
      create.mutate(
        { ...fields, image: { source: image.source, id: image.id } },
        { onSuccess: onClose },
      );
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={character !== undefined ? "Edit the character" : "Save as a character"}
      size="lg"
    >
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          A character is a picture and what to say about it. Choose it in the Talking character
          tab and its picture, description and voice fill the form. Nothing is ever deleted.
        </Text>
        {pictureUrl !== null && (
          <div style={{ width: 96 }}>
            <Thumb url={pictureUrl} width={image?.width ?? null} height={image?.height ?? null} />
          </div>
        )}
        <TextInput
          label="Name"
          value={name}
          maxLength={NAME_MAX_CHARS}
          onChange={(event) => setName(event.currentTarget.value)}
          data-autofocus
        />
        <Textarea
          label="Who they are and what they look like"
          description={`The AI that writes prompts reads this, and cannot see the picture. Describe the face, hair and clothes. ${description.trim().length} of ${CHARACTER_NOTE_MAX_CHARS} characters.`}
          value={description}
          onChange={(event) => setDescription(event.currentTarget.value)}
          maxLength={CHARACTER_NOTE_MAX_CHARS}
          autosize
          minRows={3}
        />
        <Select
          label="Default saved voice (optional)"
          description="Reads the character's lines in Clone and Direction mode."
          placeholder="None"
          data={(voices.data ?? []).map((voice) => ({
            value: String(voice.id),
            label: voice.name,
          }))}
          value={voiceId}
          onChange={setVoiceId}
          clearable
          searchable
        />
        <Textarea
          label="Default voice description (optional)"
          description={
            voiceId === null
              ? "Makes a new voice from this description (Design mode)."
              : "Steers how the saved voice speaks (Direction mode): tone, emotion, pace."
          }
          value={voiceInstruction}
          onChange={(event) => setVoiceInstruction(event.currentTarget.value)}
          maxLength={VOICE_INSTRUCTION_MAX_CHARS}
          autosize
          minRows={2}
        />
        {mutation.isError && (
          <Alert color="red" title="The character was not saved">
            {describeError(mutation.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={mutation.isPending} disabled={problem !== null} onClick={save}>
            {character !== undefined ? "Save changes" : "Save character"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
