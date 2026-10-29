import { Alert, Badge, Button, Group, Stack, Text, Tooltip } from "@mantine/core";

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

type WordTiming = NonNullable<SpeechUnitAudio["word_timing"]>;

/** How the timing of an explainer speech's words stands (EXPLAINER-007). "none" shows nothing. */
const TIMING_STATUS: Record<
  Exclude<WordTiming["status"], "none">,
  { label: string; color: string }
> = {
  in_progress: { label: "Timing words", color: "blue" },
  failed: { label: "Timing failed", color: "red" },
  timed: { label: "Words timed", color: "green" },
  estimated: { label: "Timing estimated", color: "orange" },
};

function timingHint(timing: WordTiming): string | null {
  if (timing.status === "estimated") {
    return (
      `Only ${timing.match_percent ?? 0}% of the script's words matched what was heard ` +
      `(${timing.threshold ?? 0}% needed), so each word was given its share of the speech's ` +
      `length. Heard: "${timing.heard_text ?? ""}"`
    );
  }
  if (timing.status === "timed") {
    return `${timing.match_percent ?? 0}% of the script's words matched what was heard.`;
  }
  return timing.status === "failed" ? timing.error : null;
}

export function TimingBadge({ timing }: { timing: WordTiming }) {
  if (timing.status === "none") {
    return null;
  }
  const status = TIMING_STATUS[timing.status];
  const hint = timingHint(timing);
  const badge = (
    <Badge variant="light" color={status.color}>
      {status.label}
    </Badge>
  );
  return hint === null ? (
    badge
  ) : (
    <Tooltip label={hint} multiline w={320} withArrow>
      {badge}
    </Tooltip>
  );
}

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
        {audio.word_timing !== null && <TimingBadge timing={audio.word_timing} />}
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
