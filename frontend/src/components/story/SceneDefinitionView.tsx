import { List, Stack, Table, Text } from "@mantine/core";

import type { SceneDefinition } from "../../api/sceneDefinitions";

type Rows = [label: string, value: string][];

function Section({ title, rows }: { title: string; rows: Rows }) {
  return (
    <Stack gap={2}>
      <Text size="sm" fw={600}>
        {title}
      </Text>
      <Table verticalSpacing={2}>
        <Table.Tbody>
          {rows.map(([label, value]) => (
            <Table.Tr key={label}>
              <Table.Td w={160}>
                <Text size="sm" c="dimmed">
                  {label}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm" style={{ wordBreak: "break-word" }}>
                  {value}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

/** The scene's characters, each with what it is asked to look like and how it is at the start and end. */
function Characters({ definition }: { definition: SceneDefinition }) {
  if (definition.characters.length === 0) {
    return (
      <Stack gap={2}>
        <Text size="sm" fw={600}>
          Characters
        </Text>
        <Text size="sm" c="dimmed">
          Nobody appears in this scene.
        </Text>
      </Stack>
    );
  }
  return (
    <Stack gap={2}>
      <Text size="sm" fw={600}>
        Characters
      </Text>
      <List size="sm" spacing={4}>
        {definition.characters.map((id) => (
          <List.Item key={id}>
            <Text size="sm" fw={500} component="span">
              {id}
            </Text>
            <Text size="sm" c="dimmed">
              Look requested: {definition.character_looks[id] ?? "as defined"}
            </Text>
            {definition.continuity_start[id] !== undefined && (
              <Text size="sm" c="dimmed">
                Start: {definition.continuity_start[id]}
              </Text>
            )}
            {definition.continuity_end[id] !== undefined && (
              <Text size="sm" c="dimmed">
                End: {definition.continuity_end[id]}
              </Text>
            )}
          </List.Item>
        ))}
      </List>
    </Stack>
  );
}

/**
 * One structured scene definition (`Path_ahead.md` Section 16), read only. The environment state
 * and the looks are requests in the model's own words: they are settled later, when the looks
 * and states are resolved.
 */
export function SceneDefinitionView({
  definition,
}: {
  definition: SceneDefinition;
}) {
  return (
    <Stack gap="sm">
      <Section
        title="Story context"
        rows={[
          ["Before", definition.story_context.before],
          ["This scene", definition.story_context.current],
          ["After", definition.story_context.after],
        ]}
      />
      <Section
        title="Place and time"
        rows={[
          ["Environment", definition.environment_id],
          ["State requested", definition.environment_state],
          ["Time of day", definition.time.time_of_day],
          ["Lighting", definition.time.lighting_state],
        ]}
      />
      <Characters definition={definition} />
      <Section
        title="Mood"
        rows={[
          ["Start", definition.mood.start],
          ["Middle", definition.mood.middle],
          ["End", definition.mood.end],
        ]}
      />
      <Section
        title="Dramatic goal"
        rows={[["Goal", definition.dramatic_goal]]}
      />
    </Stack>
  );
}
