import { Badge, Group, Stack, Table, Text } from "@mantine/core";
import type { ReactNode } from "react";

import type {
  ShotDefinitionContent,
  ShotStaging,
} from "../../api/shotDefinitions";

type ShotDefinitionViewProps = {
  definition: ShotDefinitionContent;
  /** The shot's staging and views, to name the view behind the shot; null when not staged. */
  staging?: ShotStaging | null;
  /** The story's characters by id, so a character is shown by name. */
  characterNames: Record<string, string>;
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Stack gap={4}>
      <Text size="xs" fw={600} c="dimmed" tt="uppercase">
        {title}
      </Text>
      {children}
    </Stack>
  );
}

/** A small two-column table of label and value, for the fields that are one phrase each. */
function Pairs({ rows }: { rows: [string, string][] }) {
  return (
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
  );
}

function sizeLabel(size: string): string {
  return size.replaceAll("_", " ");
}

/**
 * One shot's cinematic specification (`Path_ahead.md` Section 26), read only: the visual story,
 * the characters on screen, the environment state, the composition and camera, the action, the
 * continuity at each end and the audio intent. The id, duration and dialogue are written by
 * code; there is no music field.
 */
export function ShotDefinitionView({
  definition,
  staging = null,
  characterNames,
}: ShotDefinitionViewProps) {
  const nameOf = (id: string) => characterNames[id] ?? id;
  const { composition, camera, action, audio_intent: audio } = definition;
  const continuityStart = Object.entries(definition.continuity_start);
  const continuityEnd = Object.entries(definition.continuity_end);
  const environment = Object.entries(definition.environment_state);
  const view = staging?.views.find((item) => item.id === composition.view);
  const viewText =
    composition.view == null
      ? "Not set (defined before views existed)"
      : view !== undefined
        ? `${view.name} (${view.side}): ${view.description}`
        : composition.view;

  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Badge variant="outline" color="gray" style={{ textTransform: "none" }}>
          {definition.shot_id}
        </Badge>
        <Badge variant="light" color="gray">
          {definition.duration.toFixed(1)} s
        </Badge>
        <Badge variant="light" color="indigo">
          {sizeLabel(composition.shot_size)}
        </Badge>
      </Group>
      <Text size="sm">{definition.visual_story}</Text>

      <Section title="Characters on screen">
        {definition.characters.length === 0 ? (
          <Text size="sm" c="dimmed">
            Nobody is visible.
          </Text>
        ) : (
          <Table verticalSpacing={2}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Character</Table.Th>
                <Table.Th>Expression</Table.Th>
                <Table.Th>Pose</Table.Th>
                <Table.Th>Gaze</Table.Th>
                <Table.Th>Stands</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {definition.characters.map((character) => (
                <Table.Tr key={character.id}>
                  <Table.Td>{nameOf(character.id)}</Table.Td>
                  <Table.Td>{character.expression}</Table.Td>
                  <Table.Td>{character.pose}</Table.Td>
                  <Table.Td>{character.gaze}</Table.Td>
                  <Table.Td>
                    {character.zone == null
                      ? "-"
                      : `${character.zone}, ${character.screen_side ?? "?"} of the screen, ${character.background_side ?? "?"} behind`}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Section>

      <Section title="Composition and camera">
        <Pairs
          rows={[
            ["Shot size", sizeLabel(composition.shot_size)],
            ["Angle", composition.angle],
            ["View behind the shot", viewText],
            [
              "Focus",
              characterNames[composition.focus] ?? composition.focus,
            ],
            ["Camera movement", camera.movement],
            ["Camera intensity", camera.intensity],
          ]}
        />
      </Section>

      <Section title="Action">
        <Pairs
          rows={[
            ["Starts", action.start_state],
            ["Happens", action.primary_action],
            ["Ends", action.end_state],
          ]}
        />
      </Section>

      <Section title="Environment state">
        {environment.length === 0 ? (
          <Text size="sm" c="dimmed">
            Nothing noted.
          </Text>
        ) : (
          <Pairs
            rows={environment.map(([key, value]) => [
              key.replaceAll("_", " "),
              String(value),
            ])}
          />
        )}
      </Section>

      <Section title="Continuity">
        {continuityStart.length === 0 && continuityEnd.length === 0 ? (
          <Text size="sm" c="dimmed">
            Nothing to track.
          </Text>
        ) : (
          <Pairs
            rows={[
              ...continuityStart.map(
                ([id, text]): [string, string] => [
                  `${nameOf(id)}, at the start`,
                  text,
                ],
              ),
              ...continuityEnd.map(
                ([id, text]): [string, string] => [
                  `${nameOf(id)}, at the end`,
                  text,
                ],
              ),
            ]}
          />
        )}
      </Section>

      <Section title="Audio intent">
        <Pairs
          rows={[
            ["Ambient", audio.ambient],
            [
              "Sound events",
              audio.sound_events.length === 0
                ? "None"
                : audio.sound_events.join("; "),
            ],
            [
              "Dialogue",
              audio.dialogue === null
                ? "None"
                : audio.dialogue
                    .map(
                      (line) =>
                        `${nameOf(line.speaker_id)} (${line.unit_id}): ${line.text}`,
                    )
                    .join(" / "),
            ],
          ]}
        />
      </Section>
    </Stack>
  );
}
