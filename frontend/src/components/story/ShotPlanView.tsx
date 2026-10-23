import { Badge, Group, Stack, Text } from "@mantine/core";

import type { SceneEventsContent } from "../../api/sceneEvents";
import type { SpeechUnitAudio } from "../../api/speechAudio";
import type { SpeechUnitsContent } from "../../api/speechUnits";
import type { ShotPlanContent } from "../../api/shotPlans";
import { SHOT_TYPE, eventText, seconds, unitText } from "./shotPlanFormat";

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
              {shot.continues_previous && (
                <Badge
                  variant="light"
                  color="indigo"
                  style={{ flexShrink: 0 }}
                  title="No cut: this shot starts from the last frame of the shot before it"
                >
                  Continues previous shot
                </Badge>
              )}
              {shot.rapid_exchange && (
                <Badge
                  variant="light"
                  color="grape"
                  style={{ flexShrink: 0 }}
                  title="One shot with a quick back-and-forth between two characters: the clip cuts at each line"
                >
                  Rapid exchange
                </Badge>
              )}
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
