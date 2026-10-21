import { Alert, Badge, Group, Stack, Text } from "@mantine/core";

import type { SpeechUnit, SpeechUnitsContent } from "../../api/speechUnits";

const KIND_LABEL: Record<SpeechUnit["kind"], { label: string; color: string }> =
  {
    narration: { label: "Narration", color: "blue" },
    dialogue: { label: "Dialogue", color: "teal" },
  };

type SpeechUnitsViewProps = {
  units: SpeechUnitsContent;
  /** The story's characters by id, so a speaker is shown by name. */
  characterNames: Record<string, string>;
};

function UnitRow({
  unit,
  characterNames,
}: {
  unit: SpeechUnit;
  characterNames: Record<string, string>;
}) {
  const kind = KIND_LABEL[unit.kind];
  const speaker =
    unit.speaker_id !== null
      ? (characterNames[unit.speaker_id] ?? unit.speaker_id)
      : "Narrator";
  return (
    <Group align="flex-start" wrap="nowrap" gap="sm">
      <Badge
        variant="outline"
        color="gray"
        miw={56}
        style={{ flexShrink: 0, textTransform: "none" }}
      >
        {unit.id}
      </Badge>
      <Badge
        variant="light"
        color={kind.color}
        miw={90}
        style={{ flexShrink: 0 }}
      >
        {kind.label}
      </Badge>
      <Stack gap={0} style={{ flexGrow: 1 }}>
        <Text size="sm" fw={600}>
          {speaker}
          {unit.delivery && (
            <Text size="sm" c="dimmed" component="span" fw={400}>
              {" "}
              ({unit.delivery.emotion})
            </Text>
          )}
          {unit.parts > 1 && (
            <Text size="xs" c="dimmed" component="span" fw={400}>
              {" "}
              part {unit.part} of {unit.parts} of {unit.event_id}
            </Text>
          )}
        </Text>
        <Text size="sm" style={{ wordBreak: "break-word" }}>
          {unit.kind === "dialogue" ? `\u201C${unit.text}\u201D` : unit.text}
        </Text>
      </Stack>
      <Badge
        variant="light"
        color="gray"
        style={{ flexShrink: 0, textTransform: "none" }}
        title="Estimated from the words and the speech pace; the real length is measured when the speech is made"
      >
        ~{unit.estimated_seconds.toFixed(1)} s
      </Badge>
    </Group>
  );
}

/**
 * One scene's speech units in order (`Path_ahead.md` Section 19), read only, with the estimate
 * of each. A warning is shown when a piece could not be cut under its limit.
 */
export function SpeechUnitsView({
  units,
  characterNames,
}: SpeechUnitsViewProps) {
  return (
    <Stack gap="xs">
      {units.warnings.length > 0 && (
        <Alert color="yellow" p="xs" title="Over the limit">
          <Stack gap={2}>
            {units.warnings.map((warning) => (
              <Text key={`${warning.event_id}-${warning.message}`} size="sm">
                {warning.event_id}: {warning.message}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}
      {units.units.map((unit) => (
        <UnitRow key={unit.id} unit={unit} characterNames={characterNames} />
      ))}
    </Stack>
  );
}
