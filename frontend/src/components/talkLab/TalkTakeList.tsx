import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Group, Loader, Paper, Stack, Text } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";

import { describeError } from "../../api/errors";
import { useContinueTalkTake, useTalkTakes, type TalkTake } from "../../api/talkLab";
import { VIDEO_LAB_KEY } from "../../api/videoLab";
import { VOICE_LAB_KEY } from "../../api/voiceLab";
import { formatDateTime } from "../../format";
import { useNow } from "../../hooks/useNow";
import { Thumb } from "../imageLab/ReferenceTray";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { SaveVoiceModal } from "../voiceLab/SaveVoiceModal";
import { SaveCharacterModal } from "./SaveCharacterModal";
import {
  referenceFromPicture,
  STEP_LABELS,
  STEP_STATE_COLORS,
  stateFromTake,
  stepState,
  type StepState,
  type TalkFormState,
} from "./talkLabView";

type TalkTakeListProps = {
  /** Puts a take's inputs back into the form. */
  onLoad: (form: TalkFormState) => void;
  /** Makes a new clip of a take's speech, with its prompts and a new seed. */
  onReroll: (take: TalkTake) => void;
  /** The take a re-roll is being started for, or null. */
  rerolling: number | null;
};

/** The job of the step that is waiting or running now. */
function activeJobOf(take: TalkTake) {
  switch (take.running_step) {
    case "prompts":
      return take.prompt_job;
    case "voice":
      return take.voice_run?.job ?? null;
    case "video":
      return take.video_run?.job ?? null;
    default:
      return null;
  }
}

function StepBadge({ label, state }: { label: string; state: StepState }) {
  return (
    <Badge variant="light" color={STEP_STATE_COLORS[state]}>
      {label}: {state}
    </Badge>
  );
}

function FailedStep({ title, error }: { title: string; error: string }) {
  return (
    <Alert color="red" title={title} p="xs">
      <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {error}
      </Text>
    </Alert>
  );
}

function TakeCard({
  take,
  now,
  onLoad,
  onReroll,
  rerolling,
}: TalkTakeListProps & { take: TalkTake; now: number }) {
  const next = useContinueTalkTake();
  const [savingCharacter, setSavingCharacter] = useState(false);
  const [savingVoice, setSavingVoice] = useState(false);

  const voice = take.voice_run;
  const video = take.video_run;
  const speechUrl = voice?.url ?? null;
  const videoUrl = video?.url ?? null;
  const running = activeJobOf(take);
  const picture = referenceFromPicture(take.image);

  // The prompts were written by hand when no job wrote them.
  const promptsState: StepState =
    take.prompt_job === null
      ? take.video_prompt !== null
        ? "done"
        : "not started"
      : stepState(take.prompt_job, false);
  const voiceState = stepState(voice?.job, speechUrl !== null);
  const videoState = stepState(video?.job, videoUrl !== null);

  const nextStep = take.next_step;
  const blocked = nextStep === null && take.running_step === null && videoUrl === null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group align="flex-start" wrap="nowrap" gap="sm">
          {picture !== null && (
            <div style={{ width: 64, flexShrink: 0 }}>
              <Thumb url={picture.url} width={null} height={null} />
            </div>
          )}
          <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
            <Text size="sm" lineClamp={3} style={{ whiteSpace: "pre-wrap" }}>
              {take.dialogue}
            </Text>
            <Text size="xs" c="dimmed">
              {take.character !== null ? `${take.character.name} · ` : ""}
              {take.orientation}
              {take.voice_mode !== null ? ` · ${take.voice_mode} voice` : " · reused speech"} ·
              take {take.id} · {formatDateTime(take.created_at)}
            </Text>
            <Group gap="xs">
              <StepBadge label="Prompts" state={promptsState} />
              <StepBadge label="Speech" state={voiceState} />
              <StepBadge label="Video" state={videoState} />
              {take.auto_continue && (
                <Badge variant="outline" color="gray" title="Each step starts by itself when the one before has finished.">
                  runs by itself
                </Badge>
              )}
            </Group>
          </Stack>
        </Group>

        {running !== null && (
          <Group gap="xs" justify="space-between">
            <Text size="xs" c="dimmed">
              {STEP_LABELS[take.running_step ?? "prompts"]}: {running.phase ?? running.status} ·{" "}
              {elapsedText(running, now)}
              {take.running_step === "video"
                ? ". The clip takes 5 to 10 minutes. This page updates by itself."
                : ""}
            </Text>
            <JobActions job={running} />
          </Group>
        )}

        {take.last_error !== null && (
          <Alert color="orange" title="The take stopped" p="xs">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {take.last_error}
            </Text>
          </Alert>
        )}
        {take.prompt_job?.status === "failed" && take.prompt_job.error && (
          <FailedStep title="The prompts could not be written" error={take.prompt_job.error} />
        )}
        {voice?.job?.status === "failed" && voice.job.error && (
          <FailedStep title="The speech failed" error={voice.job.error} />
        )}
        {video?.job?.status === "failed" && video.job.error && (
          <FailedStep title="The video failed" error={video.job.error} />
        )}

        {speechUrl !== null && (
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Speech{voice?.duration_s != null ? ` · ${voice.duration_s.toFixed(1)} s` : ""}
            </Text>
            {/* Keyed by the run, so another speech always loads fresh. */}
            <audio
              key={voice?.id}
              src={speechUrl}
              controls
              preload="metadata"
              style={{ width: "100%" }}
            />
          </Stack>
        )}
        {videoUrl !== null && (
          <video
            key={video?.id}
            src={videoUrl}
            controls
            preload="metadata"
            playsInline
            style={{ width: "100%", maxHeight: 460, background: "#000" }}
          />
        )}

        {(take.voice_instruction !== null || take.video_prompt !== null) && (
          <Stack gap={2}>
            {take.voice_instruction !== null && (
              <Text size="xs" c="dimmed" lineClamp={2} title={take.voice_instruction}>
                Voice instruction: {take.voice_instruction}
              </Text>
            )}
            {take.video_prompt !== null && (
              <Text size="xs" c="dimmed" lineClamp={3} title={take.video_prompt}>
                Video prompt: {take.video_prompt}
              </Text>
            )}
          </Stack>
        )}

        {next.isError && (
          <Alert color="red" title="The step was not started" p="xs">
            {describeError(next.error)}
          </Alert>
        )}

        <Group gap="xs">
          {nextStep !== null && (
            <Button
              size="compact-sm"
              loading={next.isPending}
              onClick={() => next.mutate(take.id)}
              title="Starts this one step. It is a paid call."
            >
              Next: {STEP_LABELS[nextStep].toLowerCase()}
            </Button>
          )}
          <Button size="compact-sm" variant="default" onClick={() => onLoad(stateFromTake(take, false))}>
            Load into the form
          </Button>
          {speechUrl !== null && (
            <>
              <Button
                size="compact-sm"
                variant="default"
                onClick={() => onLoad(stateFromTake(take, true))}
                title="The form starts with this speech chosen, so a new clip does not pay for a new speech."
              >
                New take from this
              </Button>
              {take.video_prompt !== null && (
                <Button
                  size="compact-sm"
                  variant="default"
                  loading={rerolling === take.id}
                  disabled={rerolling !== null}
                  onClick={() => onReroll(take)}
                  title="Starts a new clip of this speech with the same prompt and a new random seed. A GPU job of 5 to 10 minutes."
                >
                  Re-roll video (same audio)
                </Button>
              )}
              <Button size="compact-sm" variant="default" onClick={() => setSavingVoice(true)}>
                Save speech as a voice
              </Button>
            </>
          )}
          <Button
            size="compact-sm"
            variant="default"
            disabled={picture === null}
            onClick={() => setSavingCharacter(true)}
          >
            Save character
          </Button>
        </Group>
        {blocked && (
          <Text size="xs" c="dimmed">
            This take has no speech it can use. Start a new take with a new or another speech.
          </Text>
        )}

        {savingCharacter && (
          <SaveCharacterModal
            key={take.id}
            opened
            onClose={() => setSavingCharacter(false)}
            image={picture}
            defaults={{
              name: take.character?.name ?? "",
              description: take.character_note ?? "",
              voiceId: take.voice_id,
              voiceInstruction: take.voice_mode === "clone" ? null : take.voice_instruction,
            }}
          />
        )}
        {savingVoice && voice !== null && (
          <SaveVoiceModal run={voice} opened onClose={() => setSavingVoice(false)} />
        )}
      </Stack>
    </Paper>
  );
}

/**
 * Every take, newest first. Each one shows its three steps, the speech and the clip once they
 * exist, and what can be done next with it.
 */
export function TalkTakeList({ onLoad, onReroll, rerolling }: TalkTakeListProps) {
  const takes = useTalkTakes();
  const queryClient = useQueryClient();
  const all = takes.data?.pages.flat() ?? [];
  const active = all.some((take) => take.running_step !== null);
  const now = useNow(active, takes.dataUpdatedAt);

  // A take that goes on by itself makes a speech and a clip the Voice and Video tabs have not
  // seen yet. When the take list shows that something started or finished, they load again.
  const signature = all
    .map((take) => `${take.id}:${take.running_step}:${take.voice_run?.id}:${take.video_run?.id}`)
    .join("|");
  const seen = useRef<string | null>(null);
  useEffect(() => {
    if (seen.current !== null && seen.current !== signature) {
      void queryClient.invalidateQueries({ queryKey: VOICE_LAB_KEY });
      void queryClient.invalidateQueries({ queryKey: VIDEO_LAB_KEY });
    }
    seen.current = signature;
  }, [signature, queryClient]);

  return (
    <Stack gap="md">
      <Text size="sm" fw={600}>
        Takes
      </Text>
      {takes.isLoading && <Loader size="sm" />}
      {takes.isError && (
        <Alert color="red" title="Could not load the takes">
          {describeError(takes.error)} Press Refresh to try again.
        </Alert>
      )}
      {takes.data && all.length === 0 && (
        <Text size="sm" c="dimmed">
          No takes yet. The takes you start appear here, and stay: they are never deleted.
        </Text>
      )}
      {all.map((take) => (
        <TakeCard
          key={take.id}
          take={take}
          now={now}
          onLoad={onLoad}
          onReroll={onReroll}
          rerolling={rerolling}
        />
      ))}
      {takes.hasNextPage && (
        <Button
          variant="default"
          onClick={() => void takes.fetchNextPage()}
          loading={takes.isFetchingNextPage}
        >
          Older takes
        </Button>
      )}
    </Stack>
  );
}
