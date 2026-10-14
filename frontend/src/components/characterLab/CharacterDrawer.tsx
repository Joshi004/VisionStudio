import { useState, type ReactNode } from "react";
import { Alert, Button, Drawer, Group, Loader, Stack, Stepper, Text, Title } from "@mantine/core";

import { useLibraryCharacter } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { LookPicker } from "./LookPicker";
import { ProfileForm } from "./ProfileForm";
import { VoiceAudition } from "./VoiceAudition";

/** The three steps of the drawer, in the order they are done. */
export type DrawerStep = 0 | 1 | 2;
export const PROFILE_STEP: DrawerStep = 0;
export const LOOK_STEP: DrawerStep = 1;
export const VOICE_STEP: DrawerStep = 2;

type DrawerBodyProps = {
  characterId: number | null;
  initialStep: DrawerStep;
  onCreated: (characterId: number) => void;
  onClose: () => void;
};

/**
 * What is inside the drawer. It is shown only while the drawer is open, so it starts afresh
 * every time: on the profile step for a new character, or on the step it was asked to open at.
 */
function DrawerBody({ characterId, initialStep, onCreated, onClose }: DrawerBodyProps) {
  // A new character gets its id when its profile is saved, and the drawer goes on to its look.
  const [id, setId] = useState<number | null>(characterId);
  const [active, setActive] = useState<DrawerStep>(initialStep);
  const character = useLibraryCharacter(id);

  /** A step that needs the saved character: waits for it, or says why it cannot be shown. */
  const showStepContent = (content: ReactNode) => {
    if (id === null) {
      return (
        <Text size="sm" c="dimmed">
          Save the profile first.
        </Text>
      );
    }
    if (character.isLoading) {
      return <Loader size="sm" />;
    }
    if (character.isError || !character.data) {
      return (
        <Alert color="red" title="Could not load the character">
          {describeError(character.error)}
        </Alert>
      );
    }
    return content;
  };

  return (
    <Stack gap="lg">
      <Stepper
        active={active}
        onStepClick={(step) => setActive(step as DrawerStep)}
        allowNextStepsSelect={id !== null}
        size="sm"
      >
        <Stepper.Step label="Profile" description="Who it is">
          {/* Keyed by the character, so the form starts from the saved profile. */}
          {id !== null && !character.data ? (
            showStepContent(null)
          ) : (
            <ProfileForm
              key={character.data?.id ?? "new"}
              character={character.data ?? null}
              onSaved={(saved, created) => {
                if (created) {
                  setId(saved.id);
                  setActive(LOOK_STEP);
                  onCreated(saved.id);
                }
              }}
            />
          )}
        </Stepper.Step>
        <Stepper.Step label="Look" description="Five pictures">
          {showStepContent(character.data && <LookPicker character={character.data} />)}
        </Stepper.Step>
        <Stepper.Step label="Voice" description="Optional">
          {showStepContent(character.data && <VoiceAudition character={character.data} />)}
        </Stepper.Step>
      </Stepper>

      <Group justify="space-between">
        <Button
          variant="default"
          disabled={active === PROFILE_STEP}
          onClick={() => setActive((step) => Math.max(PROFILE_STEP, step - 1) as DrawerStep)}
        >
          Back
        </Button>
        {active === VOICE_STEP ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <Button
            variant="default"
            disabled={id === null}
            onClick={() => setActive((step) => Math.min(VOICE_STEP, step + 1) as DrawerStep)}
          >
            {active === PROFILE_STEP ? "Next: look" : "Next: voice (optional)"}
          </Button>
        )}
      </Group>
    </Stack>
  );
}

type CharacterDrawerProps = {
  opened: boolean;
  onClose: () => void;
  /** The character to edit, or null for a new one. */
  characterId: number | null;
  /** The step to open at: Profile for a new character, Look or Voice from a character page. */
  initialStep: DrawerStep;
  /** A new character was saved: the page can show it while the drawer goes on to its look. */
  onCreated: (characterId: number) => void;
};

/**
 * Making or changing a character in one drawer, in three steps: Profile, Look and Voice. A new
 * character's profile is saved first; then its look and voice can follow, or be done later from
 * the character's page.
 */
export function CharacterDrawer({
  opened,
  onClose,
  characterId,
  initialStep,
  onCreated,
}: CharacterDrawerProps) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="xl"
      title={
        <Title order={4} component="span">
          {characterId === null ? "New character" : "Edit character"}
        </Title>
      }
    >
      <DrawerBody
        characterId={characterId}
        initialStep={initialStep}
        onCreated={onCreated}
        onClose={onClose}
      />
    </Drawer>
  );
}
