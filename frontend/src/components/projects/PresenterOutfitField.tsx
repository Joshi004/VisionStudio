import { useState } from "react";
import { Alert, Select, Stack, Textarea } from "@mantine/core";

import { useCharacterOutfits } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { OUTFIT_MAX_CHARS } from "./projectKinds";

const DEFAULT_CHOICE = "default";
const NEW_CHOICE = "new";

type PresenterOutfitFieldProps = {
  /** The presenter's id in the Character Lab; null until one is chosen. */
  characterId: number | null;
  /** The saved outfit that is picked, or null. */
  pickedId: number | null;
  /** The typed outfit; only used when no saved outfit is picked. */
  text: string;
  /** An outfit the project picked earlier that is no longer in the Lab, kept as it is. */
  deletedPick?: { id: number; name: string } | null;
  onChange: (value: { pickedId: number | null; text: string }) => void;
};

/**
 * What an explainer's presenter wears: the default outfit, one of the presenter's saved outfits,
 * or a new outfit described in words. Picking a saved outfit makes no text; describing one
 * clears the pick.
 */
export function PresenterOutfitField({
  characterId,
  pickedId,
  text,
  deletedPick = null,
  onChange,
}: PresenterOutfitFieldProps) {
  const outfits = useCharacterOutfits(characterId);
  const [describing, setDescribing] = useState(text.trim() !== "");

  const saved = (outfits.data ?? []).filter((outfit) => !outfit.is_default && outfit.id !== null);
  const options = [
    { value: DEFAULT_CHOICE, label: "Default (the character's usual outfit)" },
    ...saved.map((outfit) => ({
      value: String(outfit.id),
      label: outfit.note ? `${outfit.name} - ${outfit.note}` : outfit.name,
    })),
    ...(deletedPick !== null && !saved.some((outfit) => outfit.id === deletedPick.id)
      ? [{ value: String(deletedPick.id), label: `${deletedPick.name} (deleted)` }]
      : []),
    { value: NEW_CHOICE, label: "Describe a new outfit" },
  ];
  const choice = pickedId !== null ? String(pickedId) : describing ? NEW_CHOICE : DEFAULT_CHOICE;

  function choose(value: string | null) {
    if (value === null || value === DEFAULT_CHOICE) {
      setDescribing(false);
      onChange({ pickedId: null, text: "" });
    } else if (value === NEW_CHOICE) {
      setDescribing(true);
      onChange({ pickedId: null, text });
    } else {
      setDescribing(false);
      onChange({ pickedId: Number(value), text: "" });
    }
  }

  return (
    <Stack gap="xs">
      <Select
        label="Presenter outfit (optional)"
        description="What the presenter wears in this video: the usual outfit, one saved in the Character Lab, or a new one described in words. A new outfit is also saved for the character."
        value={choice}
        onChange={choose}
        data={options}
        allowDeselect={false}
        disabled={characterId === null}
        placeholder={characterId === null ? "Choose a presenter first" : undefined}
      />
      {outfits.isError && <Alert color="red">{describeError(outfits.error)}</Alert>}
      {choice === NEW_CHOICE && (
        <Textarea
          aria-label="New outfit"
          description="For example: a navy blazer over a white shirt. New pictures of the presenter in this outfit are made for the project."
          value={text}
          onChange={(event) => onChange({ pickedId: null, text: event.currentTarget.value })}
          maxLength={OUTFIT_MAX_CHARS}
          autosize
          minRows={2}
          maxRows={4}
        />
      )}
    </Stack>
  );
}
