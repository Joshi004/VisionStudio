import { useRef } from "react";
import { Alert, Button, FileButton, Group, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useUploadVoiceover, VOICEOVER_MAX_MB, type ProjectDetail } from "../../api/projects";
import { audioFormatLabel, formatBytes, formatDuration } from "../../format";

export function VoiceoverSection({ project }: { project: ProjectDetail }) {
  const upload = useUploadVoiceover(project.id);
  // Lets the same file be picked again after a failed upload.
  const resetFileButton = useRef<() => void>(null);
  const { voiceover } = project;

  function chooseFile(file: File | null) {
    resetFileButton.current?.();
    if (file) {
      upload.mutate(file);
    }
  }

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
              {voiceover.duration_s?.toFixed(2)} s) · {formatBytes(voiceover.size_bytes)} · uploaded{" "}
              {new Date(voiceover.created_at).toLocaleString()}
            </Text>
          </>
        )}

        {!voiceover && <Text c="dimmed">No voiceover yet.</Text>}

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
      </Stack>
    </Paper>
  );
}
