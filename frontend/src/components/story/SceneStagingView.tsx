import { Badge, Group, Stack, Table, Text } from "@mantine/core";

import type { SceneStagingContent } from "../../api/sceneStaging";

type SceneStagingViewProps = {
  staging: SceneStagingContent;
  /** The story's characters by id, so a character is shown by name. */
  characterNames: Record<string, string>;
};

/** One scene's staging, read only: who stands where, and what is behind each of them. */
export function SceneStagingView({ staging, characterNames }: SceneStagingViewProps) {
  const name = (id: string) => characterNames[id] ?? id;
  const axis = staging.axis;
  return (
    <Stack gap="xs">
      <Table verticalSpacing={2}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Character</Table.Th>
            <Table.Th>Zone</Table.Th>
            <Table.Th>Posture</Table.Th>
            <Table.Th>Faces</Table.Th>
            <Table.Th>Screen side</Table.Th>
            <Table.Th>Behind them</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {staging.placements.map((placement) => (
            <Table.Tr key={placement.character_id}>
              <Table.Td>{name(placement.character_id)}</Table.Td>
              <Table.Td>{placement.zone}</Table.Td>
              <Table.Td>{placement.posture}</Table.Td>
              <Table.Td>{characterNames[placement.faces] ?? placement.faces}</Table.Td>
              <Table.Td>{placement.screen_side}</Table.Td>
              <Table.Td>{placement.background_side}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {(staging.off_screen ?? []).length > 0 && (
        <Text size="sm" c="dimmed">
          Only heard, not placed: {(staging.off_screen ?? []).map(name).join(", ")}
        </Text>
      )}
      <Group gap="xs">
        <Badge variant="light" color="gray">
          Group background: {staging.group_side}
        </Badge>
        {axis.between.length === 2 && (
          <Badge variant="light" color="gray">
            Axis: {name(axis.between[0])} and {name(axis.between[1])}
            {axis.camera_half !== null ? `, camera on the ${axis.camera_half} side` : ""}
          </Badge>
        )}
      </Group>
      {axis.note !== "" && (
        <Text size="sm" c="dimmed">
          {axis.note}
        </Text>
      )}
      {staging.moves.length > 0 && (
        <Stack gap={2}>
          <Text size="sm" fw={600}>
            Moves
          </Text>
          {staging.moves.map((move, index) => (
            <Text key={index} size="sm">
              After {move.after_event_id}: {name(move.character_id)} goes to {move.zone}, faces{" "}
              {characterNames[move.faces] ?? move.faces}, {move.screen_side} of the screen,{" "}
              {move.background_side} behind them.
            </Text>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
