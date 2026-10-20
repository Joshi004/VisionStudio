import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  UnstyledButton,
} from "@mantine/core";

import { useLibraryCharacters, type LibraryCharacter } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { characterSubtitle, frontPicture } from "./characterLabView";

type CharacterLibraryProps = {
  onOpen: (characterId: number) => void;
  onNew: () => void;
};

function CharacterCard({ character, onOpen }: { character: LibraryCharacter; onOpen: () => void }) {
  const picture = frontPicture(character);
  return (
    <Paper withBorder radius="md" p="xs">
      <UnstyledButton onClick={onOpen} style={{ display: "block", width: "100%" }}>
        <Stack gap={6}>
          {picture !== null ? (
            <img
              src={picture}
              alt={`${character.name}, front view`}
              loading="lazy"
              style={{
                width: "100%",
                aspectRatio: "2 / 3",
                objectFit: "contain",
                background: "var(--mantine-color-gray-1)",
                borderRadius: 4,
                display: "block",
              }}
            />
          ) : (
            <div
              style={{
                width: "100%",
                aspectRatio: "2 / 3",
                background: "var(--mantine-color-gray-1)",
                borderRadius: 4,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Text size="xs" c="dimmed">
                No look yet
              </Text>
            </div>
          )}
          <Text size="sm" fw={600} lineClamp={1} title={character.name}>
            {character.name}
          </Text>
          <Text size="xs" c="dimmed" lineClamp={1} title={characterSubtitle(character)}>
            {characterSubtitle(character)}
          </Text>
          <Group gap={4}>
            {character.voice !== null ? (
              <Badge variant="light" color="grape" title={character.voice.name}>
                voice
              </Badge>
            ) : (
              <Badge variant="light" color="gray">
                mute
              </Badge>
            )}
            {character.archived && (
              <Badge variant="light" color="orange">
                archived
              </Badge>
            )}
            {character.origin !== null && (
              <Badge
                variant="light"
                color="teal"
                title={`Made from the project ${character.origin.project_name}`}
              >
                from project
              </Badge>
            )}
          </Group>
        </Stack>
      </UnstyledButton>
    </Paper>
  );
}

/**
 * The library: every character as a card, newest first. Archived characters are hidden unless
 * asked for. A character is never deleted.
 */
export function CharacterLibrary({ onOpen, onNew }: CharacterLibraryProps) {
  const [showArchived, setShowArchived] = useState(false);
  const library = useLibraryCharacters(showArchived);
  const characters = library.data?.pages.flatMap((page) => page.characters) ?? [];

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" maw={680}>
          Your characters: a profile, five pictures on a white backdrop, and a voice if it has one.
          Open one to make pictures, speech and clips that look and sound the same every time.
        </Text>
        <Group gap="md">
          <Switch
            label="Show archived"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.currentTarget.checked)}
          />
          <Button onClick={onNew}>New character</Button>
        </Group>
      </Group>

      {library.isLoading && <Loader size="sm" />}
      {library.isError && (
        <Alert color="red" title="Could not load the characters">
          {describeError(library.error)}
        </Alert>
      )}
      {library.data && characters.length === 0 && (
        <Text size="sm" c="dimmed">
          {showArchived ? "No characters yet." : "No characters yet. Press New character."}
        </Text>
      )}

      <SimpleGrid cols={{ base: 2, sm: 3, md: 4, lg: 5 }} spacing="sm">
        {characters.map((character) => (
          <CharacterCard key={character.id} character={character} onOpen={() => onOpen(character.id)} />
        ))}
      </SimpleGrid>

      {library.hasNextPage && (
        <Group>
          <Button
            variant="default"
            loading={library.isFetchingNextPage}
            onClick={() => void library.fetchNextPage()}
          >
            Older
          </Button>
        </Group>
      )}
    </Stack>
  );
}
