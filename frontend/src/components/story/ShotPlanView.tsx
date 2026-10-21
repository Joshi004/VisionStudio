import { Badge, Group, Stack, Text } from "@mantine/core";

import type { SceneEvent, SceneEventsContent } from "../../api/sceneEvents";
import type { SpeechUnitAudio } from "../../api/speechAudio";
import type { SpeechUnit, SpeechUnitsContent } from "../../api/speechUnits";
import type { Shot, ShotPlanContent } from "../../api/shotPlans";

const SHOT_TYPE: Record<Shot["type"], { label: string; color: string }> = {
  establishing: { label: "Establishing", color: "indigo" },
  action: { label: "Action", color: "grape" },
  reaction: { label: "Reaction", color: "pink" },
  dialogue: { label: "Dialogue", color: "teal" },
  insert: { label: "Insert", color: "orange" },
  transition: { label: "Transition", color: "gray" },
};

const EVENT_LABEL: Record<SceneEvent["type"], string> = {
  narration: "Narration",
  dialogue: "Dialogue",
  action: "Action",
  sound_event: "Sound",
  pause: "Pause",
};

type ShotPlanViewProps = {
  plan: ShotPlanContent;
  /** The scene's events and speech units, so a shot can name what it shows and carries. */
  events: SceneEventsContent | null;
  units: SpeechUnitsContent | null;
  /** The audio of the scene's units, for the measured length of each. */
  audio: SpeechUnitAudio[];
  /** The story's characters by id, so a speaker is shown by name. */
  characterNames: Record<string, string>;
};

function shorten(text: string, limit = 70): string {
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}...`;
}

function seconds(value: number): string {
  return `${value.toFixed(1)} s`;
}

function eventText(event: SceneEvent, characterNames: Record<string, string>) {
  const body = event.text ?? event.description ?? "";
  const speaker =
    event.speaker_id != null
      ? (characterNames[event.speaker_id] ?? event.speaker_id)
      : null;
  const label = EVENT_LABEL[event.type];
  const prefix = speaker !== null ? `${label}, ${speaker}` : label;
  return body === "" ? prefix : `${prefix}: ${shorten(body)}`;
}

function unitText(unit: SpeechUnit, characterNames: Record<string, string>) {
  const speaker =
    unit.speaker_id != null
      ? (characterNames[unit.speaker_id] ?? unit.speaker_id)
      : "Narrator";
  return `${speaker}: ${shorten(unit.text)}`;
}

/**
 * One scene's shots in story order (`Path_ahead.md` Section 25), read only. A shot names the
 * events it shows and the speech units heard while it plays. A narration unit that continues
 * from the shot before is marked, since one recording can span several shots.
 */
export function ShotPlanView({
  plan,
  events,
  units,
  audio,
  characterNames,
}: ShotPlanViewProps) {
  const eventsById = new Map((events?.events ?? []).map((e) => [e.id, e]));
  const unitsById = new Map((units?.units ?? []).map((u) => [u.id, u]));
  const measured = new Map(
    audio.flatMap((item) =>
      item.audio ? [[item.unit_id, item.audio.measured_seconds] as const] : [],
    ),
  );

  return (
    <Stack gap="sm">
      {plan.shots.map((shot, position) => {
        const type = SHOT_TYPE[shot.type];
        const previous = position > 0 ? plan.shots[position - 1] : null;
        return (
          <Stack key={shot.id} gap={4}>
            <Group gap="xs" wrap="nowrap" align="flex-start">
              <Badge
                variant="outline"
                color="gray"
                miw={64}
                style={{ flexShrink: 0, textTransform: "none" }}
              >
                {shot.id}
              </Badge>
              <Badge
                variant="light"
                color={type.color}
                miw={100}
                style={{ flexShrink: 0 }}
              >
                {type.label}
              </Badge>
              <Badge variant="light" color="gray" style={{ flexShrink: 0 }}>
                {seconds(shot.target_duration)}
              </Badge>
              <Text size="sm" style={{ wordBreak: "break-word" }}>
                {shot.description}
              </Text>
            </Group>
            <Stack gap={0} ml={72}>
              {shot.source_event_ids.map((eventId) => {
                const event = eventsById.get(eventId);
                return (
                  <Text key={eventId} size="xs" c="dimmed">
                    {eventId}
                    {event ? ` \u00B7 ${eventText(event, characterNames)}` : ""}
                  </Text>
                );
              })}
              {shot.speech_unit_ids.map((unitId) => {
                const unit = unitsById.get(unitId);
                const length = measured.get(unitId);
                const continues = previous?.speech_unit_ids.includes(unitId);
                return (
                  <Text key={unitId} size="xs" c="blue.8">
                    {unitId}
                    {unit ? ` \u00B7 ${unitText(unit, characterNames)}` : ""}
                    {length !== undefined ? ` (${seconds(length)})` : ""}
                    {continues ? " \u00B7 continues from the shot before" : ""}
                  </Text>
                );
              })}
            </Stack>
          </Stack>
        );
      })}
    </Stack>
  );
}
