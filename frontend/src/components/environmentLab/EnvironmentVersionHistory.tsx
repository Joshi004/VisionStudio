import { Accordion, Alert, Badge, Group, Loader, Stack, Text } from "@mantine/core";

import { useEnvironmentVersions, type EnvironmentVersion } from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import { formatDateTime } from "../../format";
import { eraText, VERSION_CHANGE_LABELS } from "./environmentLabView";

const PICTURE_STYLE = {
  width: "100%",
  aspectRatio: "16 / 9",
  objectFit: "cover",
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

function VersionDetails({ version }: { version: EnvironmentVersion }) {
  const { profile } = version;
  return (
    <Stack gap="sm">
      <Stack gap={4}>
        <Row label="Name" value={profile.name} />
        <Row label="Era" value={eraText(profile)} />
        <Row label="Description" value={profile.description} />
        <Row label="Atmosphere" value={profile.atmosphere} />
        <Row label="Notes" value={profile.notes} />
      </Stack>
      {version.image !== null ? (
        <img
          src={version.image.url}
          alt={`Reference picture, version ${version.version}`}
          loading="lazy"
          style={PICTURE_STYLE}
        />
      ) : (
        <Text size="xs" c="dimmed">
          No picture was chosen for this version.
        </Text>
      )}
    </Stack>
  );
}

/**
 * The versions of one environment, newest first, read-only. A version is a snapshot of the
 * profile made when it changed, with the picture chosen for it. It is never edited, so an old
 * version always shows what it was and the picture it was made for.
 */
export function EnvironmentVersionHistory({ environmentId }: { environmentId: number }) {
  const versions = useEnvironmentVersions(environmentId);

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
                      {VERSION_CHANGE_LABELS[change]}
                    </Badge>
                  ))}
                  <Badge
                    variant="light"
                    color={version.image !== null ? "blue" : "gray"}
                    size="sm"
                  >
                    {version.image !== null ? "picture" : "no picture"}
                  </Badge>
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
