import { Alert, Badge, Group, Stack, Text } from "@mantine/core";

import type { SceneEvent, SceneEventsContent } from "../../api/sceneEvents";

const TYPE_LABEL: Record<SceneEvent["type"], { label: string; color: string }> =
  {
    narration: { label: "Narration", color: "blue" },
    dialogue: { label: "Dialogue", color: "teal" },
    action: { label: "Action", color: "grape" },
    sound_event: { label: "Sound", color: "orange" },
    pause: { label: "Pause", color: "gray" },
  };

type SceneEventsViewProps = {
  events: SceneEventsContent;
  /** The story's characters by id, so a speaker is shown by name. */
  characterNames: Record<string, string>;
};

function EventRow({
  event,
  characterNames,
}: {
  event: SceneEvent;
  characterNames: Record<string, string>;
}) {
  const type = TYPE_LABEL[event.type];
  const speaker =
    event.speaker_id != null
      ? (characterNames[event.speaker_id] ?? event.speaker_id)
      : null;
  const body = event.text ?? event.description ?? null;
  return (
    <Group align="flex-start" wrap="nowrap" gap="sm">
      <Badge
        variant="outline"
        color="gray"
        miw={56}
        style={{ flexShrink: 0, textTransform: "none" }}
      >
        {event.id}
      </Badge>
      <Badge
        variant="light"
        color={type.color}
        miw={90}
        style={{ flexShrink: 0 }}
      >
        {type.label}
      </Badge>
      <Stack gap={0} style={{ flexGrow: 1 }}>
        {speaker !== null && (
          <Text size="sm" fw={600}>
            {speaker}
            {event.delivery && (
              <Text size="sm" c="dimmed" component="span" fw={400}>
                {" "}
                ({event.delivery.emotion})
              </Text>
            )}
          </Text>
        )}
        {body !== null && (
          <Text size="sm" style={{ wordBreak: "break-word" }}>
            {event.type === "dialogue" ? `\u201C${body}\u201D` : body}
          </Text>
        )}
      </Stack>
    </Group>
  );
}

/**
 * One scene's events in story order (`Path_ahead.md` Section 17), read only. Text of the scene
 * that no narration or dialogue event covers is shown in yellow after the event it follows: it
 * is a warning, not an error, because a sentence such as "Thump." legitimately becomes a sound.
 */
export function SceneEventsView({
  events,
  characterNames,
}: SceneEventsViewProps) {
  const uncoveredAfter = (eventId: string | null) =>
    events.uncovered.filter((piece) => piece.after_event_id === eventId);

  return (
    <Stack gap="xs">
      {events.uncovered.length > 0 && (
        <Alert color="yellow" p="xs" title="Text not covered by speech">
          {events.uncovered.length} piece
          {events.uncovered.length === 1 ? "" : "s"} of the scene&apos;s text
          {events.uncovered.length === 1 ? " is" : " are"} not spoken by any
          narration or dialogue event. This is expected when the text became an
          action or a sound.
        </Alert>
      )}
      {uncoveredAfter(null).map((piece) => (
        <Text key={`start-${piece.text}`} size="xs" c="yellow.8">
          Not covered: {piece.text}
        </Text>
      ))}
      {events.events.map((event) => (
        <Stack key={event.id} gap={2}>
          <EventRow event={event} characterNames={characterNames} />
          {uncoveredAfter(event.id).map((piece) => (
            <Text
              key={`${event.id}-${piece.text}`}
              size="xs"
              c="yellow.8"
              ml={160}
            >
              Not covered: {piece.text}
            </Text>
          ))}
        </Stack>
      ))}
    </Stack>
  );
}
