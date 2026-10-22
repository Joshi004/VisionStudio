import { useEffect } from "react";
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { useLibraryCharacters } from "../../api/characterLab";
import { useCharacterLinks } from "../../api/characterLinks";
import { useEnvironmentLinks } from "../../api/environmentLinks";
import { useLibraryEnvironments } from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import {
  CAST_MODE_LABELS,
  useProjectCast,
  useRemoveCastMember,
  useSetCastMember,
  type CastKind,
  type CastMember,
  type CastMode,
} from "../../api/projectCast";

type CastPanelProps = {
  projectId: number;
};

type PickerOption = { value: string; label: string };

const MODE_OPTIONS = (Object.keys(CAST_MODE_LABELS) as CastMode[]).map((mode) => ({
  value: mode,
  label: CAST_MODE_LABELS[mode],
}));

type CastSectionProps = {
  title: string;
  singular: string;
  members: CastMember[];
  // Library items that are not in the cast yet.
  options: PickerOption[];
  // For each library id, the name of the story entry that is linked to it.
  usedFor: Map<number, string>;
  disabled: boolean;
  onAdd: (libraryId: number) => void;
  onMode: (libraryId: number, mode: CastMode) => void;
  onRemove: (libraryId: number) => void;
};

/** One kind of the cast: its members, each with a mode, and a picker to add more. */
function CastSection({
  title,
  singular,
  members,
  options,
  usedFor,
  disabled,
  onAdd,
  onMode,
  onRemove,
}: CastSectionProps) {
  return (
    <Stack gap={6}>
      <Text size="sm" fw={500}>
        {title}
      </Text>

      {members.length === 0 && (
        <Text size="sm" c="dimmed">
          None yet.
        </Text>
      )}

      {members.map((member) => {
        const entryName = usedFor.get(member.library_id);
        return (
          <Group key={member.library_id} gap="xs" align="center">
            <Text size="sm" fw={500} miw={140}>
              {member.name}
            </Text>
            <Select
              aria-label={`What to do with ${member.name}`}
              size="xs"
              w={210}
              allowDeselect={false}
              data={MODE_OPTIONS}
              value={member.mode}
              disabled={disabled}
              onChange={(value) => {
                if (value !== null) {
                  onMode(member.library_id, value as CastMode);
                }
              }}
            />
            {entryName !== undefined ? (
              <Badge variant="light" title="The story entry that is linked to this item">
                used for {entryName}
              </Badge>
            ) : (
              <Badge variant="light" color="gray">
                not used in this story
              </Badge>
            )}
            {member.archived && (
              <Badge
                variant="light"
                color="orange"
                title="An archived item is not offered to the model"
              >
                archived
              </Badge>
            )}
            <Button
              size="compact-xs"
              variant="subtle"
              color="red"
              disabled={disabled}
              onClick={() => onRemove(member.library_id)}
              title="Takes it out of the cast. It stays in the lab."
            >
              Remove
            </Button>
          </Group>
        );
      })}

      <Select
        aria-label={`Add a ${singular} to the cast`}
        size="xs"
        w={300}
        searchable
        placeholder={
          options.length === 0 ? `No other ${title.toLowerCase()} in the lab` : `Add a ${singular}`
        }
        nothingFoundMessage={`No such ${singular}`}
        data={options}
        value={null}
        disabled={disabled || options.length === 0}
        onChange={(value) => {
          if (value !== null) {
            onAdd(Number(value));
          }
        }}
      />
    </Stack>
  );
}

/**
 * The library characters and environments the user wants to reuse in this story. The cast is
 * shown to the model when the story's characters and environments are found: it can say that
 * one of them is a cast member, and the pipeline then links it to that library item instead of
 * making a new one. Each member has a mode: use it as it is, or keep its look and write the text
 * again for this story.
 */
export function CastPanel({ projectId }: CastPanelProps) {
  const { data, isLoading, isError, error } = useProjectCast(projectId);
  const characterLibrary = useLibraryCharacters(false);
  const environmentLibrary = useLibraryEnvironments(false);
  const characterLinks = useCharacterLinks(projectId);
  const environmentLinks = useEnvironmentLinks(projectId);
  const setMember = useSetCastMember(projectId);
  const removeMember = useRemoveCastMember(projectId);

  // The pickers list the whole library, so the pages are loaded one after the other.
  const characterNext = characterLibrary.hasNextPage && !characterLibrary.isFetchingNextPage;
  const fetchMoreCharacters = characterLibrary.fetchNextPage;
  useEffect(() => {
    if (characterNext) {
      void fetchMoreCharacters();
    }
  }, [characterNext, fetchMoreCharacters]);
  const environmentNext = environmentLibrary.hasNextPage && !environmentLibrary.isFetchingNextPage;
  const fetchMoreEnvironments = environmentLibrary.fetchNextPage;
  useEffect(() => {
    if (environmentNext) {
      void fetchMoreEnvironments();
    }
  }, [environmentNext, fetchMoreEnvironments]);

  const busy = setMember.isPending || removeMember.isPending;
  const failed = [setMember, removeMember].find((mutation) => mutation.isError);

  const characters = data?.characters ?? [];
  const environments = data?.environments ?? [];

  const characterOptions = (characterLibrary.data?.pages ?? [])
    .flatMap((page) => page.characters)
    .filter((item) => !characters.some((member) => member.library_id === item.id))
    .map((item) => ({ value: String(item.id), label: `${item.name} (#${item.id})` }));
  const environmentOptions = (environmentLibrary.data?.pages ?? [])
    .flatMap((page) => page.environments)
    .filter((item) => !environments.some((member) => member.library_id === item.id))
    .map((item) => ({ value: String(item.id), label: `${item.name} (#${item.id})` }));

  const characterUse = new Map<number, string>(
    (characterLinks.data?.entries ?? []).flatMap((entry) =>
      entry.link ? [[entry.link.character_id, entry.name] as [number, string]] : [],
    ),
  );
  const environmentUse = new Map<number, string>(
    (environmentLinks.data?.entries ?? []).flatMap((entry) =>
      entry.link ? [[entry.link.environment_id, entry.name] as [number, string]] : [],
    ),
  );

  const add = (kind: CastKind) => (libraryId: number) =>
    setMember.mutate({ kind, libraryId, mode: "as_is" });
  const changeMode = (kind: CastKind) => (libraryId: number, mode: CastMode) =>
    setMember.mutate({ kind, libraryId, mode });
  const remove = (kind: CastKind) => (libraryId: number) =>
    removeMember.mutate({ kind, libraryId });

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Stack gap={2}>
          <Title order={4}>Cast</Title>
          <Text size="sm" c="dimmed">
            Characters and environments you already made in the lab. When the story&apos;s
            characters and environments are found, the model may say that one of them is a cast
            member, and it is then linked to it instead of a new one being made. Use as is keeps
            its definition, look and voice (or picture). Keep look, rewrite text keeps its look
            and voice (or picture) and writes the text again for this story. Changing the cast
            makes the found characters and environments out of date, so they are found again.
          </Text>
        </Stack>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the cast">
            {describeError(error)}
          </Alert>
        )}
        {failed && (
          <Alert color="red" title="The cast was not changed">
            {describeError(failed.error)}
          </Alert>
        )}

        {data && (
          <>
            <Divider />
            <CastSection
              title="Characters"
              singular="character"
              members={characters}
              options={characterOptions}
              usedFor={characterUse}
              disabled={busy}
              onAdd={add("characters")}
              onMode={changeMode("characters")}
              onRemove={remove("characters")}
            />
            <Divider />
            <CastSection
              title="Environments"
              singular="environment"
              members={environments}
              options={environmentOptions}
              usedFor={environmentUse}
              disabled={busy}
              onAdd={add("environments")}
              onMode={changeMode("environments")}
              onRemove={remove("environments")}
            />
          </>
        )}
      </Stack>
    </Paper>
  );
}
