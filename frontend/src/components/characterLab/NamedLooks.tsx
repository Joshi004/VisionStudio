import { Alert, Badge, Group, Loader, Stack, Text } from "@mantine/core";

import { useNamedLooks } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { ReferenceStrip } from "./LookPicker";

/**
 * The named looks of one character, such as night clothes, read-only. A story project's
 * resolution creates each one, and its pictures are made from the character's canonical front
 * picture. They never replace the character's current look.
 */
export function NamedLooks({ characterId }: { characterId: number }) {
  const looks = useNamedLooks(characterId);

  if (looks.data?.length === 0) {
    return null;
  }
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Named looks
      </Text>
      {looks.isLoading && <Loader size="xs" />}
      {looks.isError && (
        <Alert color="red" p="xs" title="Could not load the named looks">
          {describeError(looks.error)}
        </Alert>
      )}
      {looks.data?.map((named) => (
        <Stack key={named.id} gap={4}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {named.name}
            </Text>
            <Badge variant="outline" color="gray" size="sm" style={{ textTransform: "none" }}>
              {named.slug}
            </Badge>
            <Badge variant="light" color={named.look?.status === "ready" ? "green" : "gray"} size="sm">
              {named.look?.status === "ready" ? "pictures ready" : "no pictures yet"}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {named.description}
          </Text>
          {named.look !== null && named.look.status === "ready" && (
            <ReferenceStrip look={named.look} />
          )}
        </Stack>
      ))}
    </Stack>
  );
}
