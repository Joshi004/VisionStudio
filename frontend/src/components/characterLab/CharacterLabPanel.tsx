import { useState } from "react";

import { CharacterDrawer, PROFILE_STEP, type DrawerStep } from "./CharacterDrawer";
import { CharacterLibrary } from "./CharacterLibrary";
import { CharacterPage } from "./CharacterPage";
import { useOpenCharacter } from "./useOpenCharacter";

type DrawerConfig = {
  opened: boolean;
  /** The character to edit, or null for a new one. */
  characterId: number | null;
  step: DrawerStep;
};

/**
 * The Characters tab: the library, or one character's page when the address says which
 * (`?character=`). Making or changing a character happens in a drawer over either of them.
 * Nothing here is kept in the Lab page: a character, its looks and takes live on the server.
 */
export function CharacterLabPanel() {
  const [openId, openCharacter] = useOpenCharacter();
  // `opened` is kept apart from the rest, so the drawer does not change its title while it
  // slides out.
  const [drawer, setDrawer] = useState<DrawerConfig>({
    opened: false,
    characterId: null,
    step: PROFILE_STEP,
  });

  return (
    <>
      {openId === null ? (
        <CharacterLibrary
          onOpen={openCharacter}
          onNew={() => setDrawer({ opened: true, characterId: null, step: PROFILE_STEP })}
        />
      ) : (
        <CharacterPage
          characterId={openId}
          onBack={() => openCharacter(null)}
          onEdit={(step) => setDrawer({ opened: true, characterId: openId, step })}
        />
      )}
      <CharacterDrawer
        opened={drawer.opened}
        onClose={() => setDrawer((current) => ({ ...current, opened: false }))}
        characterId={drawer.characterId}
        initialStep={drawer.step}
        onCreated={(characterId) => {
          // The new character's page shows behind the drawer while its look is made.
          setDrawer((current) => ({ ...current, characterId }));
          openCharacter(characterId);
        }}
      />
    </>
  );
}
