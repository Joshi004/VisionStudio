import { Stack, Table, Text } from "@mantine/core";

import type { CharacterDefinition } from "../../api/characterDefinitions";
import { eraText } from "./characterLabView";

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

/**
 * One structured character definition (`Path_ahead.md` Section 11), read only: how the character
 * looks, what they wear by default, how they sound and how they behave, and when their story is
 * set. The same view is used in the story workspace and in the Character lab.
 */
export function CharacterDefinitionView({ definition }: { definition: CharacterDefinition }) {
  const visual = definition.visual_identity;
  const wardrobe = definition.default_wardrobe;
  const voice = definition.voice_identity;
  const behavior = definition.behavior;
  return (
    <Stack gap="sm">
      <Section
        title="Visual identity"
        rows={[
          ["Apparent age", visual.apparent_age === null ? "—" : String(visual.apparent_age)],
          ["Sex", visual.sex],
          ["Species", visual.species],
          ["Visible mouth", visual.has_visible_mouth ? "Yes" : "No (no lip sync)"],
          ["Build", visual.build],
          ["Height", visual.height_character],
          ["Skin tone", visual.skin_tone],
          ["Face shape", visual.face_shape],
          ["Hair", visual.hair],
          ["Eyes", visual.eyes],
          ["Distinctive features", visual.distinctive_features],
        ]}
      />
      <Section
        title="Default wardrobe"
        rows={[
          ["Upper", wardrobe.upper],
          ["Lower", wardrobe.lower],
          ["Footwear", wardrobe.footwear],
        ]}
      />
      <Section
        title="Voice identity"
        rows={[
          ["Age", voice.age_character],
          ["Pitch", voice.pitch],
          ["Texture", voice.texture],
          ["Accent", voice.accent],
          ["Default energy", voice.default_energy],
        ]}
      />
      <Section
        title="Behaviour"
        rows={[
          ["Baseline", behavior.baseline],
          ["Gesture style", behavior.gesture_style],
        ]}
      />
      <Section
        title="Era"
        rows={[
          [
            "Story set",
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
