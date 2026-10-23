import { useEffect, useState } from "react";
import {
  Alert,
  Anchor,
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
import { Link } from "react-router";

import {
  useCharacterLinks,
  useCreateLink,
  useLinkAll,
  useMapLink,
  useSetCharacterVersion,
  useUnlink,
  type LinkedCharacter,
} from "../../api/characterLinks";
import { useCharacterVersions, useLibraryCharacters } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { CAST_MODE_LABELS, useProjectCast, type CastMode } from "../../api/projectCast";

type CharacterLinksPanelProps = {
  projectId: number;
};

function labPath(characterId: number): string {
  return `/lab/characters?character=${characterId}`;
}

/**
 * Chooses which version of the character the project pins (PHASE-042), newer or older. The
 * versions are loaded when the list is opened. Only the pin moves: what depends on the
 * character goes out of date, and **Regenerate out-of-date** rebuilds it.
 */
function VersionPicker({
  characterId,
  pinned,
  disabled,
  onChange,
}: {
  characterId: number;
  pinned: number;
  disabled: boolean;
  onChange: (version: number) => void;
}) {
  const [opened, setOpened] = useState(false);
  const versions = useCharacterVersions(opened ? characterId : null);
  const options = (versions.data ?? []).map((version) => {
    const changes = version.changes.filter((change) => change !== "created").join(", ");
    const who = version.source === "ai" ? "pipeline" : "edited in the lab";
    return {
      value: String(version.version),
      label: `v${version.version}: ${who}${changes ? ` (${changes})` : ""}`,
    };
  });
  return (
    <Select
      aria-label="Change the version this project uses"
      size="xs"
      w={230}
      allowDeselect={false}
      data={options.length > 0 ? options : [{ value: String(pinned), label: `v${pinned}` }]}
      value={String(pinned)}
      disabled={disabled}
      onDropdownOpen={() => setOpened(true)}
      onChange={(value) => {
        if (value !== null && Number(value) !== pinned) {
          onChange(Number(value));
        }
      }}
    />
  );
}

/** Where a linked entry points: the library character, the version pinned, and what is newer. */
function LinkedLine({
  link,
  castMode,
  disabled,
  onUnlink,
  onChangeVersion,
}: {
  link: LinkedCharacter;
  // The mode of the cast member the entry is linked to, or undefined when it is not in the cast.
  castMode: CastMode | undefined;
  disabled: boolean;
  onUnlink: () => void;
  onChangeVersion: (version: number) => void;
}) {
  return (
    <Group gap="xs">
      <Anchor component={Link} to={labPath(link.character_id)} size="sm" fw={500}>
        {link.name}
      </Anchor>
      <Badge variant="light" color="gray" title="How the link was made">
        {link.how === "created" ? "made for this project" : "chosen from the library"}
      </Badge>
      <Badge variant="light" title="The version of the character this project uses">
        pins v{link.pinned_version}
      </Badge>
      {castMode !== undefined && link.how === "mapped" && (
        <Badge
          variant="light"
          color="teal"
          title="This item is in the project's cast, so the pipeline reuses it without asking."
        >
          from cast: {CAST_MODE_LABELS[castMode].toLowerCase()}
        </Badge>
      )}
      {link.newer_version_available && (
        <Badge
          variant="light"
          color="yellow"
          title="The Character Lab has a newer version. The project keeps the pinned one until you choose to adopt the new one."
        >
          newer version available (v{link.newest_version})
        </Badge>
      )}
      {link.archived && (
        <Badge variant="light" color="orange">
          archived
        </Badge>
      )}
      <VersionPicker
        characterId={link.character_id}
        pinned={link.pinned_version}
        disabled={disabled}
        onChange={onChangeVersion}
      />
      <Button
        size="compact-xs"
        variant="subtle"
        color="red"
        disabled={disabled}
        onClick={onUnlink}
        title="Removes the link. The character stays in the Character Lab."
      >
        Unlink
      </Button>
    </Group>
  );
}

/**
 * The project's discovered characters, each backed by a Character Lab character and pinned to
 * one of its versions. An entry can be **created** in the lab from the discovery (name and
 * one-line description), or **mapped** to a character that already exists, which lets a
 * character be reused across projects. A pin never moves because of a lab edit: the lab having
 * a newer version is only shown, and the version picker (or **Adopt** in the lab) moves it.
 */
export function CharacterLinksPanel({ projectId }: CharacterLinksPanelProps) {
  const { data, isLoading, isError, error } = useCharacterLinks(projectId);
  const library = useLibraryCharacters(false);
  const linkAll = useLinkAll(projectId);
  const create = useCreateLink(projectId);
  const map = useMapLink(projectId);
  const unlink = useUnlink(projectId);
  const setVersion = useSetCharacterVersion(projectId);
  const cast = useProjectCast(projectId);

  // The picker lists the whole library, so the pages are loaded one after the other.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = library;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // The cast members by library id, to mark the entries that were linked from the cast.
  const castModes = new Map<number, CastMode>(
    (cast.data?.characters ?? []).map(
      (member) => [member.library_id, member.mode] as [number, CastMode],
    ),
  );

  // One change at a time: every button waits for the one before it.
  const busy =
    linkAll.isPending ||
    create.isPending ||
    map.isPending ||
    unlink.isPending ||
    setVersion.isPending;
  const failed = [linkAll, create, map, unlink, setVersion].find((mutation) => mutation.isError);

  const entries = data?.entries ?? [];
  const orphaned = data?.orphaned ?? [];
  const unlinkedCount = entries.filter((entry) => entry.link === null).length;

  // A library character is used for one entry of a project, so the ones already linked are not
  // offered again.
  const used = new Set<number>([
    ...entries.flatMap((entry) => (entry.link ? [entry.link.character_id] : [])),
    ...orphaned.map((link) => link.character_id),
  ]);
  const options = (library.data?.pages ?? [])
    .flatMap((page) => page.characters)
    .filter((character) => !used.has(character.id))
    .map((character) => ({
      value: String(character.id),
      label:
        character.version === null
          ? `${character.name} (#${character.id})`
          : `${character.name} (#${character.id}, v${character.version})`,
    }));

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Library links</Title>
            <Text size="sm" c="dimmed">
              Each character is backed by a Character Lab character, and the project pins one
              version of it. A change made in the lab never moves the pin: choose a version here to move it.
            </Text>
          </Stack>
          <Button
            onClick={() => linkAll.mutate()}
            loading={linkAll.isPending}
            disabled={isLoading || isError || busy || unlinkedCount === 0}
          >
            Link all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the links">
            {describeError(error)}
          </Alert>
        )}
        {failed && (
          <Alert color="red" title="The change was not made">
            {describeError(failed.error)}
          </Alert>
        )}
        {data && data.discovery_version === null && (
          <Text size="sm" c="dimmed">
            Find the characters first (above). Then link them to the Character Lab here.
          </Text>
        )}

        {entries.length > 0 && (
          <>
            <Text size="sm" c="dimmed">
              {entries.length - unlinkedCount} of {entries.length} linked, from version{" "}
              {data?.discovery_version} of the list.
            </Text>
            <Divider />
          </>
        )}

        {entries.map((entry) => (
          <Stack key={entry.id} gap={6}>
            <Group align="flex-start" wrap="nowrap" gap="sm">
              <Badge
                variant="outline"
                color="gray"
                miw={120}
                style={{ flexShrink: 0, textTransform: "none" }}
              >
                {entry.id}
              </Badge>
              <Stack gap={0}>
                <Text size="sm" fw={500}>
                  {entry.name}
                </Text>
                <Text size="sm" c="dimmed">
                  {entry.description}
                </Text>
              </Stack>
            </Group>
            <Group pl={136}>
              {entry.link ? (
                <LinkedLine
                  link={entry.link}
                  castMode={castModes.get(entry.link.character_id)}
                  disabled={busy}
                  onUnlink={() => unlink.mutate(entry.id)}
                  onChangeVersion={(version) =>
                    setVersion.mutate({ discoveryId: entry.id, version })
                  }
                />
              ) : (
                <Group gap="xs">
                  <Button
                    size="compact-sm"
                    variant="default"
                    loading={create.isPending && create.variables === entry.id}
                    disabled={busy}
                    onClick={() => create.mutate(entry.id)}
                  >
                    Create in lab
                  </Button>
                  <Select
                    aria-label={`Use an existing character for ${entry.name}`}
                    size="xs"
                    w={240}
                    searchable
                    clearable={false}
                    placeholder={
                      options.length === 0
                        ? "No other characters in the lab"
                        : "Use an existing character"
                    }
                    nothingFoundMessage="No such character"
                    data={options}
                    value={null}
                    disabled={busy || options.length === 0}
                    onChange={(value) => {
                      if (value !== null) {
                        map.mutate({ discoveryId: entry.id, characterId: Number(value) });
                      }
                    }}
                  />
                </Group>
              )}
            </Group>
          </Stack>
        ))}

        {orphaned.length > 0 && (
          <>
            <Divider />
            <Stack gap={6}>
              <Text size="sm" fw={500}>
                Linked earlier, not in the newest list
              </Text>
              <Text size="sm" c="dimmed">
                The characters were found again with different ids. These links are kept, and
                apply again if a later run brings the id back.
              </Text>
              {orphaned.map((link) => (
                <Group key={link.discovery_id} gap="sm" wrap="nowrap" align="flex-start">
                  <Badge
                    variant="outline"
                    color="gray"
                    miw={120}
                    style={{ flexShrink: 0, textTransform: "none" }}
                  >
                    {link.discovery_id}
                  </Badge>
                  <LinkedLine
                    link={link}
                    castMode={castModes.get(link.character_id)}
                    disabled={busy}
                    onUnlink={() => unlink.mutate(link.discovery_id)}
                    onChangeVersion={(version) =>
                      setVersion.mutate({ discoveryId: link.discovery_id, version })
                    }
                  />
                </Group>
              ))}
            </Stack>
          </>
        )}
      </Stack>
    </Paper>
  );
}
