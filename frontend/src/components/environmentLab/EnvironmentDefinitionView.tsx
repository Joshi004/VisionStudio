import { List, Stack, Table, Text } from "@mantine/core";

import type { EnvironmentDefinition } from "../../api/environmentDefinitions";
import { eraText } from "./environmentLabView";

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

function ItemList({ title, items }: { title: string; items: string[] }) {
  return (
    <Stack gap={2}>
      <Text size="sm" fw={600}>
        {title}
      </Text>
      <List size="sm" spacing={2}>
        {items.map((item) => (
          <List.Item key={item}>{item}</List.Item>
        ))}
      </List>
    </Stack>
  );
}

/**
 * One structured environment definition (`Path_ahead.md` Section 13), read only: the place's
 * architecture and layout, how its surfaces look, the landmarks that make it recognisable, its
 * usual mood, what must stay the same, and when it is set. The same view is used in the story
 * workspace and in the Character lab.
 */
export function EnvironmentDefinitionView({ definition }: { definition: EnvironmentDefinition }) {
  const visual = definition.visual_identity;
  return (
    <Stack gap="sm">
      <Section
        title="Place"
        rows={[
          ["Architecture", definition.architecture],
          ["Layout", definition.layout],
        ]}
      />
      <Section
        title="Visual identity"
        rows={[
          ["Walls", visual.walls],
          ["Floor", visual.floor],
          ["Windows", visual.windows],
          ["Doors", visual.doors],
          ["Furniture", visual.furniture],
          ["Colour palette", visual.color_palette],
        ]}
      />
      <ItemList title="Important landmarks" items={definition.important_landmarks} />
      <Section title="Atmosphere" rows={[["Baseline", definition.atmosphere.baseline]]} />
      <ItemList title="Continuity rules" items={definition.continuity_rules} />
      <Section
        title="Era"
        rows={[
          [
            "Set",
            eraText({
              era_kind: definition.era.kind,
              era_years: definition.era.years,
              era_setting: definition.era.setting,
            }),
          ],
        ]}
      />
    </Stack>
  );
}
