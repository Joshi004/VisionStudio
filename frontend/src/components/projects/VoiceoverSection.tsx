import { useRef } from "react";
import {
  Alert,
  Button,
  Divider,
  FileButton,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useUpdateProject,
  useUploadVoiceover,
  VOICEOVER_MAX_MB,
  type ProjectDetail,
} from "../../api/projects";
import { useGenerateVoiceover, useVoiceoverGeneration, useVoices } from "../../api/voiceLab";
import { audioFormatLabel, formatBytes, formatDuration } from "../../format";
import { useNow } from "../../hooks/useNow";
import { useRefreshWhenFinished } from "../../hooks/useRefreshWhenFinished";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { LicenseNotice } from "../voiceLab/LicenseNotice";

/**
 * The project's voiceover: uploaded, or made from the script by Breeze TTS in a saved voice
 * (voices are added in the Voice lab). The transcription that follows is the same either way.
 */
export function VoiceoverSection({ project }: { project: ProjectDetail }) {
  const upload = useUploadVoiceover(project.id);
  const updateProject = useUpdateProject(project.id);
  const voices = useVoices();
  const generation = useVoiceoverGeneration(project.id);
  const generate = useGenerateVoiceover(project.id);
  // Lets the same file be picked again after a failed upload.
  const resetFileButton = useRef<() => void>(null);
  const { voiceover } = project;

  const job = generation.data?.job ?? null;
  const isActive = isJobActive(job);
  // Elapsed times are worked out from the stored times and the clock, which ticks once a
  // second while the job is waiting or running. When it finishes, the whole page is loaded.
  const now = useNow(isActive, generation.dataUpdatedAt);
  useRefreshWhenFinished(isActive);

  function chooseFile(file: File | null) {
    resetFileButton.current?.();
    if (file) {
      upload.mutate(file);
    }
  }

  const blocked = isActive ? "The voiceover is being made." : (generation.data?.blocked ?? null);
  const madeByApp = voiceover?.source === "ai";

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Voiceover</Title>

        {voiceover && (
          <>
            {/* Keyed by the asset, so a replacement loads fresh instead of reusing the old file. */}
            <audio
              key={voiceover.asset_id}
              controls
              preload="metadata"
              src={voiceover.url}
              style={{ width: "100%" }}
            />
            <Text size="sm" c="dimmed">
              {audioFormatLabel(voiceover.mime)} · {formatDuration(voiceover.duration_s ?? 0)} (
              {voiceover.duration_s?.toFixed(2)} s) · {formatBytes(voiceover.size_bytes)} ·{" "}
              {madeByApp ? "made from the script" : "uploaded"}{" "}
              {new Date(voiceover.created_at).toLocaleString()}
            </Text>
          </>
        )}

        {!voiceover && <Text c="dimmed">No voiceover yet.</Text>}

        {madeByApp && generation.data && !generation.data.voiceover_current && (
          <Alert color="yellow" title="The script has changed since this voiceover was made">
            Make the voiceover again to match the script, then transcribe again.
          </Alert>
        )}

        <Group gap="sm">
          <FileButton
            resetRef={resetFileButton}
            onChange={chooseFile}
            accept=".wav,.mp3,.m4a,.flac,audio/*"
          >
            {(props) => (
              <Button {...props} loading={upload.isPending}>
                {voiceover ? "Replace voiceover" : "Upload voiceover"}
              </Button>
            )}
          </FileButton>
          <Text size="xs" c="dimmed">
            {upload.isPending
              ? "Uploading and checking..."
              : `WAV, MP3, M4A or FLAC, up to ${VOICEOVER_MAX_MB} MB.${
                  voiceover ? " The previous file is kept." : ""
                }`}
          </Text>
        </Group>

        {upload.isError && (
          <Alert color="red" title="The voiceover was not saved">
            {describeError(upload.error)}
          </Alert>
        )}

        <Divider label="or make it from the script" labelPosition="left" />

        <Group align="flex-end" gap="sm">
          <Select
            label="Voice"
            placeholder={voices.data?.length === 0 ? "No saved voices yet" : "Choose a voice"}
            data={(voices.data ?? []).map((voice) => ({
              value: String(voice.id),
              label: voice.name,
            }))}
            value={project.voice_id === null ? null : String(project.voice_id)}
            onChange={(value) =>
              updateProject.mutate({ voice_id: value === null ? null : Number(value) })
            }
            clearable
            searchable
            disabled={isActive}
            w={260}
          />
          <Button
            onClick={() => generate.mutate()}
            loading={generate.isPending}
            disabled={blocked !== null}
          >
            {voiceover ? "Make the voiceover again" : "Make the voiceover"}
          </Button>
          {blocked !== null && (
            <Text size="xs" c="dimmed">
              {blocked}
            </Text>
          )}
        </Group>
        <Text size="xs" c="dimmed">
          Breeze TTS speaks the script in the chosen voice, 1000 characters at a time, and the result
          replaces the voiceover above (the old file is kept). Add voices in the Voice lab.
        </Text>
        <LicenseNotice />

        {updateProject.isError && (
          <Alert color="red" title="The voice was not saved">
            {describeError(updateProject.error)}
          </Alert>
        )}
        {generate.isError && (
          <Alert color="red" title="The voiceover was not started">
            {describeError(generate.error)}
          </Alert>
        )}

        {job && (
          <Stack gap={4}>
            <Group gap="sm">
              <JobStatusBadge job={job} />
              <Text size="sm" c="dimmed">
                {elapsedText(job, now)}
              </Text>
            </Group>
            {isActive && (
              <Text size="xs" c="dimmed">
                Each 1000 characters take one to three minutes. This updates by itself.
              </Text>
            )}
          </Stack>
        )}

        {job?.status === "failed" && job.error && (
          <Alert color="red" title="The voiceover could not be made">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {job.error}
            </Text>
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
