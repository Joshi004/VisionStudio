import { Alert, Badge, Group, MultiSelect, Select, Stack, Text } from "@mantine/core";

import { useCast, useSetSceneCast, type CastMember } from "../../api/cast";
import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import type { Scene } from "../../api/scenes";

/** The members as the choices of a MultiSelect (nothing chosen means none). */
function memberChoices(members: CastMember[]) {
  return members.map((member) => ({ value: String(member.id), label: member.name }));
}

/** The members as the choices of a Select, with "None" first. */
function choices(members: CastMember[]) {
  return [{ value: "", label: "None" }, ...memberChoices(members)];
}

/**
 * Which characters and which place this scene shows, from the project's cast. The AI chooses
 * them (Choose who is in each scene), and a choice made here is the user's own: the AI never
 * replaces it. A scene shows any characters (the order they are chosen in is the order of their
 * pictures) and at most one place, and its first frame is made from their pictures. Nothing is
 * shown while the project has no cast.
 */
export function SceneCastPicker({ project, scene }: { project: ProjectDetail; scene: Scene }) {
  const { data: cast } = useCast(project.id);
  const save = useSetSceneCast(project.id);

  if (cast === undefined || (cast.characters.length === 0 && cast.locations.length === 0)) {
    return null;
  }

  function choose(characterIds: number[], locationId: number | null) {
    save.mutate({ sceneId: scene.id, characterIds, locationId });
  }

  const source = scene.cast_assignment_source;

  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text size="sm" fw={500}>
          Who and where
        </Text>
        {source === "ai" && (
          <Badge color="grape" variant="light">
            Chosen by the AI
          </Badge>
        )}
        {source === "manual" && (
          <Badge color="gray" variant="light">
            Chosen by you
          </Badge>
        )}
        {source === null && (
          <Badge color="gray" variant="outline">
            Not chosen yet
          </Badge>
        )}
      </Group>
      <Group gap="sm" grow align="flex-start">
        <MultiSelect
          label="Characters"
          placeholder="None"
          data={memberChoices(cast.characters)}
          value={scene.character_ids.map(String)}
          onChange={(values) => choose(values.map(Number), scene.location_id)}
          disabled={save.isPending}
        />
        <Select
          label="Place"
          data={choices(cast.locations)}
          value={scene.location_id === null ? "" : String(scene.location_id)}
          onChange={(value) => choose(scene.character_ids, value ? Number(value) : null)}
          allowDeselect={false}
          disabled={save.isPending}
        />
      </Group>
      <Text size="xs" c="dimmed">
        Any characters, and one place at most. After a change, write the image prompt again: it is
        written for the pictures of the cast the scene shows.
      </Text>
      {save.isError && (
        <Alert color="red" title="The choice was not saved">
          {describeError(save.error)}
        </Alert>
      )}
    </Stack>
  );
}
