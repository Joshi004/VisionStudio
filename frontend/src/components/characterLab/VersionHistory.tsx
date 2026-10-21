import { Accordion, Alert, Badge, Group, Loader, SimpleGrid, Stack, Text } from "@mantine/core";

import { useCharacterVersions, type CharacterVersion } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { formatDateTime } from "../../format";
import {
  ANGLE_LABELS,
  eraText,
  referencePicture,
  VERSION_CHANGE_LABELS,
} from "./characterLabView";
import { CharacterDefinitionView } from "./CharacterDefinitionView";

const PICTURE_STYLE = {
  width: "100%",
  aspectRatio: "2 / 3",
  objectFit: "contain",
  background: "var(--mantine-color-gray-1)",
  borderRadius: 4,
  display: "block",
} as const;

function Row({ label, value }: { label: string; value: string | null }) {
  if (value === null || value.trim() === "") {
    return null;
  }
  return (
    <Text size="sm">
      <Text span fw={500}>
        {label}:{" "}
      </Text>
      {value}
    </Text>
  );
}

/** "Look 2" for a change of look, else the plain word. */
function changeLabel(version: CharacterVersion, change: CharacterVersion["changes"][number]): string {
  if (change === "look" && version.look_version !== null) {
    return `${VERSION_CHANGE_LABELS.look} ${version.look_version}`;
  }
  return VERSION_CHANGE_LABELS[change];
}

function VersionDetails({ version }: { version: CharacterVersion }) {
  const { profile } = version;
  return (
    <Stack gap="sm">
      <Stack gap={4}>
        <Row label="Name" value={profile.name} />
        <Row label="Species" value={profile.species} />
        <Row label="Age" value={profile.age === null ? null : String(profile.age)} />
        <Row label="Gender" value={profile.gender} />
        <Row label="Era" value={eraText(profile)} />
        <Row label="Appearance" value={profile.appearance} />
        <Row label="Outfit" value={profile.outfit} />
        <Row label="Personality" value={profile.personality} />
        <Row label="Notes" value={profile.notes} />
        <Row label="Mouth" value={profile.has_visible_mouth ? "visible" : "not visible (no lip sync)"} />
        <Row label="Voice" value={version.voice?.name ?? "mute"} />
        <Row label="Voice description" value={version.voice_description} />
      </Stack>
      {version.definition !== null && (
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            Definition
          </Text>
          <CharacterDefinitionView definition={version.definition} />
        </Stack>
      )}
      {version.references.length === 0 ? (
        <Text size="xs" c="dimmed">
          No look in this version.
        </Text>
      ) : (
        <SimpleGrid cols={5} spacing={4}>
          {version.references.map((reference) => {
            const picture = referencePicture(reference);
            return (
              <Stack key={reference.angle} gap={2}>
                {picture !== null ? (
                  <img
                    src={picture}
                    alt={`${ANGLE_LABELS[reference.angle]} view, version ${version.version}`}
                    loading="lazy"
                    style={PICTURE_STYLE}
                  />
                ) : (
                  <div style={PICTURE_STYLE} />
                )}
                <Text size="xs" c="dimmed" ta="center">
                  {ANGLE_LABELS[reference.angle]}
                </Text>
              </Stack>
            );
          })}
        </SimpleGrid>
      )}
      {version.named_looks.map((named) => (
        <Stack key={named.slug} gap={4}>
          <Text size="sm" fw={600}>
            Named look: {named.name}
          </Text>
          <SimpleGrid cols={5} spacing={4}>
            {named.references.map((reference) => {
              const picture = referencePicture(reference);
              return (
                <Stack key={reference.angle} gap={2}>
                  {picture !== null ? (
                    <img
                      src={picture}
                      alt={`${named.name}, ${ANGLE_LABELS[reference.angle]} view, version ${version.version}`}
                      loading="lazy"
                      style={PICTURE_STYLE}
                    />
                  ) : (
                    <div style={PICTURE_STYLE} />
                  )}
                  <Text size="xs" c="dimmed" ta="center">
                    {ANGLE_LABELS[reference.angle]}
                  </Text>
                </Stack>
              );
            })}
          </SimpleGrid>
        </Stack>
      ))}
    </Stack>
  );
}

/**
 * The versions of one character, newest first, read-only. A version is a snapshot of the
 * profile, the voice and the look (with its exact pictures) at the moment one of them changed;
 * it is never edited, so an old version always shows what it was.
 */
export function VersionHistory({ characterId }: { characterId: number }) {
  const versions = useCharacterVersions(characterId);

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Version history
      </Text>
      {versions.isLoading && <Loader size="xs" />}
      {versions.isError && (
        <Alert color="red" p="xs" title="Could not load the versions">
          {describeError(versions.error)}
        </Alert>
      )}
      {versions.data?.length === 0 && (
        <Text size="xs" c="dimmed">
          No versions yet. The next change to the profile, the voice or the look makes the first.
        </Text>
      )}
      {versions.data !== undefined && versions.data.length > 0 && (
        <Accordion variant="contained">
          {versions.data.map((version) => (
            <Accordion.Item key={version.id} value={String(version.id)}>
              <Accordion.Control>
                <Group gap="xs">
                  <Text size="sm" fw={500}>
                    Version {version.version}
                  </Text>
                  {version.changes.map((change) => (
                    <Badge key={change} variant="light" color="gray" size="sm">
                      {changeLabel(version, change)}
                    </Badge>
                  ))}
                  <Text size="xs" c="dimmed">
                    {formatDateTime(version.created_at)}
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <VersionDetails version={version} />
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  );
}
