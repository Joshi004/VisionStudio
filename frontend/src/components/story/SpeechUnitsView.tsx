import { Alert, Badge, Button, Group, Stack, Text } from "@mantine/core";

import type { SpeechUnitAudio } from "../../api/speechAudio";
import type { SpeechUnit, SpeechUnitsContent } from "../../api/speechUnits";

const KIND_LABEL: Record<SpeechUnit["kind"], { label: string; color: string }> =
  {
    narration: { label: "Narration", color: "blue" },
    dialogue: { label: "Dialogue", color: "teal" },
  };

const AUDIO_STATUS: Record<
  SpeechUnitAudio["status"],
  { label: string; color: string }
> = {
  unavailable: { label: "Cannot be made", color: "gray" },
  none: { label: "Not made", color: "gray" },
  in_progress: { label: "Being made", color: "blue" },
  failed: { label: "Failed", color: "red" },
  ready: { label: "Made", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

type SpeechUnitsViewProps = {
  units: SpeechUnitsContent;
  /** The story's characters by id, so a speaker is shown by name. */
  characterNames: Record<string, string>;
  /**
   * Where the audio of each unit stands, by unit id (PHASE-019). Left out, the units are shown
   * with their estimates only.
   */
  audio?: Record<string, SpeechUnitAudio>;
  /** True while a speech is being started, so no second press is made. */
  busy?: boolean;
  onMake?: (unitId: string) => void;
};

type AudioLineProps = {
  unitId: string;
  audio: SpeechUnitAudio;
  busy: boolean;
  onMake?: (unitId: string) => void;
};

/**
 * What is known of one unit's speech: its status, the voice and mode, the player with the
 * measured length, why it is out of date or cannot be made, and the button to make it.
 */
function AudioLine({ unitId, audio, busy, onMake }: AudioLineProps) {
  const status = AUDIO_STATUS[audio.status];
  const label =
    audio.status === "none" || audio.status === "unavailable"
      ? "Make"
      : audio.status === "failed"
        ? "Retry"
        : "Make again";
  return (
    <Stack gap={4} pl={146}>
      <Group gap="xs" align="center">
        <Badge variant="light" color={status.color}>
          {status.label}
        </Badge>
        {audio.voice_name !== null && (
          <Text size="xs" c="dimmed">
            {audio.voice_name}
            {audio.mode === "direction" ? ", directed" : ", cloned"}
          </Text>
        )}
        {onMake && (
          <Button
            size="compact-xs"
            variant="default"
            disabled={!audio.can_run || busy}
            onClick={() => onMake(unitId)}
          >
            {label}
          </Button>
        )}
      </Group>
      {audio.audio !== null && (
        <audio
          src={audio.audio.url}
          controls
          preload="metadata"
          style={{ width: "100%", maxWidth: 420 }}
        />
      )}
      {audio.reasons.map((reason) => (
        <Text key={reason} size="xs" c="yellow.8">
          {reason}
        </Text>
      ))}
      {audio.error !== null && (
        <Text size="xs" c="red">
          {audio.error}
        </Text>
      )}
      {audio.blocked_reason !== null && audio.status !== "in_progress" && (
        <Text size="xs" c="dimmed">
          {audio.blocked_reason}
        </Text>
      )}
    </Stack>
  );
}

function UnitRow({
  unit,
  characterNames,
  audio,
  busy,
  onMake,
}: {
  unit: SpeechUnit;
  characterNames: Record<string, string>;
  audio: SpeechUnitAudio | undefined;
  busy: boolean;
  onMake?: (unitId: string) => void;
}) {
  const kind = KIND_LABEL[unit.kind];
  const speaker =
    unit.speaker_id !== null
      ? (characterNames[unit.speaker_id] ?? unit.speaker_id)
      : "Narrator";
  const measured = audio?.audio?.measured_seconds ?? null;
  return (
    <Stack gap={4}>
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
        <Stack gap={2} align="flex-end" style={{ flexShrink: 0 }}>
          <Badge
            variant="light"
            color="gray"
            style={{ textTransform: "none" }}
            title="Estimated from the words and the speech pace; the real length is measured when the speech is made"
          >
            ~{unit.estimated_seconds.toFixed(1)} s
          </Badge>
          {measured !== null && (
            <Badge
              variant="filled"
              color="green"
              style={{ textTransform: "none" }}
              title="Measured from the speech that was made"
            >
              {measured.toFixed(1)} s
            </Badge>
          )}
        </Stack>
      </Group>
      {audio !== undefined && (
        <AudioLine unitId={unit.id} audio={audio} busy={busy} onMake={onMake} />
      )}
    </Stack>
  );
}

/**
 * One scene's speech units in order (`Path_ahead.md` Section 19), with the estimate of each. A
 * warning is shown when a piece could not be cut under its limit. With `audio`, each unit also
 * shows its speech (`Path_ahead.md` Section 20): the player and the measured length.
 */
export function SpeechUnitsView({
  units,
  characterNames,
  audio,
  busy = false,
  onMake,
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
        <UnitRow
          key={unit.id}
          unit={unit}
          characterNames={characterNames}
          audio={audio?.[unit.id]}
          busy={busy}
          onMake={onMake}
        />
      ))}
    </Stack>
  );
}
