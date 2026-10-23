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

import { useEnvironmentVersions, useLibraryEnvironments } from "../../api/environmentLab";
import {
  useCreateEnvironmentLink,
  useEnvironmentLinks,
  useLinkAllEnvironments,
  useMapEnvironmentLink,
  useSetEnvironmentVersion,
  useUnlinkEnvironment,
  type LinkedEnvironment,
} from "../../api/environmentLinks";
import { describeError } from "../../api/errors";
import { CAST_MODE_LABELS, useProjectCast, type CastMode } from "../../api/projectCast";

type EnvironmentLinksPanelProps = {
  projectId: number;
};

function labPath(environmentId: number): string {
  return `/lab/environments?environment=${environmentId}`;
}

/**
 * Chooses which version of the environment the project pins (PHASE-042), newer or older. The
 * versions are loaded when the list is opened. A version with no picture cannot be chosen. Only
 * the pin moves: what depends on the environment goes out of date, and **Regenerate
 * out-of-date** rebuilds it.
 */
function VersionPicker({
  environmentId,
  pinned,
  disabled,
  onChange,
}: {
  environmentId: number;
  pinned: number;
  disabled: boolean;
  onChange: (version: number) => void;
}) {
  const [opened, setOpened] = useState(false);
  const versions = useEnvironmentVersions(opened ? environmentId : null);
  const options = (versions.data ?? []).map((version) => {
    const changes = version.changes.filter((change) => change !== "created").join(", ");
    const who = version.source === "ai" ? "pipeline" : "edited in the lab";
    return {
      value: String(version.version),
      label: `v${version.version}: ${who}${changes ? ` (${changes})` : ""}${
        version.image === null ? ", no picture" : ""
      }`,
      disabled: version.image === null && version.version !== pinned,
    };
  });
  return (
    <Select
      aria-label="Change the version this project uses"
      size="xs"
      w={260}
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

/** Where a linked entry points: the library environment, the version pinned, and what is newer. */
function LinkedLine({
  link,
  castMode,
  disabled,
  onUnlink,
  onChangeVersion,
}: {
  link: LinkedEnvironment;
  // The mode of the cast member the entry is linked to, or undefined when it is not in the cast.
  castMode: CastMode | undefined;
  disabled: boolean;
  onUnlink: () => void;
  onChangeVersion: (version: number) => void;
}) {
  return (
    <Group gap="xs">
      <Anchor component={Link} to={labPath(link.environment_id)} size="sm" fw={500}>
        {link.name}
      </Anchor>
      <Badge variant="light" color="gray" title="How the link was made">
        {link.how === "created" ? "made for this project" : "chosen from the library"}
      </Badge>
      <Badge variant="light" title="The version of the environment this project uses">
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
          title="The Character Lab has a newer version. The project keeps the pinned one until you adopt it."
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
        environmentId={link.environment_id}
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
        title="Removes the link. The environment stays in the Character Lab."
      >
        Unlink
      </Button>
    </Group>
  );
}

/**
 * The project's discovered environments, each backed by a Character Lab environment and pinned
 * to one of its versions. An entry can be **created** in the lab from the discovery (name and
 * one-line description), or **mapped** to an environment that already exists, which lets a place
 * be reused across projects. A pin never moves because of a lab edit: the lab having a newer
 * version is only shown, and the version picker (or **Adopt** in the lab) moves it.
 */
export function EnvironmentLinksPanel({ projectId }: EnvironmentLinksPanelProps) {
  const { data, isLoading, isError, error } = useEnvironmentLinks(projectId);
  const library = useLibraryEnvironments(false);
  const linkAll = useLinkAllEnvironments(projectId);
  const create = useCreateEnvironmentLink(projectId);
  const map = useMapEnvironmentLink(projectId);
  const unlink = useUnlinkEnvironment(projectId);
  const setVersion = useSetEnvironmentVersion(projectId);
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
    (cast.data?.environments ?? []).map(
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

  // A library environment is used for one entry of a project, so the ones already linked are not
  // offered again.
  const used = new Set<number>([
    ...entries.flatMap((entry) => (entry.link ? [entry.link.environment_id] : [])),
    ...orphaned.map((link) => link.environment_id),
  ]);
  const options = (library.data?.pages ?? [])
    .flatMap((page) => page.environments)
    .filter((environment) => !used.has(environment.id))
    .map((environment) => ({
      value: String(environment.id),
      label:
        environment.version === null
          ? `${environment.name} (#${environment.id})`
          : `${environment.name} (#${environment.id}, v${environment.version})`,
    }));

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Environment library links</Title>
            <Text size="sm" c="dimmed">
              Each environment is backed by a Character Lab environment, and the project pins one
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
            Find the environments first (above). Then link them to the Character Lab here.
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
                  castMode={castModes.get(entry.link.environment_id)}
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
                    aria-label={`Use an existing environment for ${entry.name}`}
                    size="xs"
                    w={240}
                    searchable
                    clearable={false}
                    placeholder={
                      options.length === 0
                        ? "No other environments in the lab"
                        : "Use an existing environment"
                    }
                    nothingFoundMessage="No such environment"
                    data={options}
                    value={null}
                    disabled={busy || options.length === 0}
                    onChange={(value) => {
                      if (value !== null) {
                        map.mutate({ discoveryId: entry.id, environmentId: Number(value) });
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
                The environments were found again with different ids. These links are kept, and
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
                    castMode={castModes.get(link.environment_id)}
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
