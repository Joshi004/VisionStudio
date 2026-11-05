import { Badge, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import type { GraphicVoice } from "../../api/graphicsLab";
import { TIMING_SOURCE_LABELS, voiceStageText } from "./graphicsLabView";

type GraphicsVoicePanelProps = {
  voice: GraphicVoice;
};

/**
 * The voice of a run (GFX-004): which saved voice reads the line, whether its speech is made and
 * its words are timed, how well Parakeet's words matched the line, and the speech alone to play.
 * The brief waits until the timing is stored.
 */
export function GraphicsVoicePanel({ voice }: GraphicsVoicePanelProps) {
  const working = voice.state === "speaking" || voice.state === "timing";

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text size="xs" fw={600} c="dimmed">
              Voice
            </Text>
            <Text size="sm">{voice.voice_name ?? "A saved voice that was deleted"}</Text>
          </Stack>
          <Group gap="xs">
            {working && <Loader size="xs" />}
            <Badge variant="light" color={voice.state === "failed" ? "red" : voice.state === "ready" ? "green" : "blue"}>
              {voiceStageText(voice.state)}
            </Badge>
          </Group>
        </Group>

        {voice.state === "ready" && voice.timing_source !== null && (
          <Text size="xs" c="dimmed">
            Times are {TIMING_SOURCE_LABELS[voice.timing_source] ?? voice.timing_source}
            {voice.match_percent !== null && voice.threshold !== null
              ? `: ${voice.match_percent}% of the line was heard, and ${voice.threshold}% is needed.`
              : "."}
          </Text>
        )}
        {voice.note && (
          <Text size="xs" c="orange" style={{ wordBreak: "break-word" }}>
            {voice.note}
          </Text>
        )}
        {voice.error && (
          <Text size="sm" c="red" style={{ wordBreak: "break-word" }}>
            {voice.error}
          </Text>
        )}

        {/* The speech alone, to compare with the times of the beats. */}
        {voice.speech_url !== null && (
          <audio controls preload="none" src={voice.speech_url} style={{ width: "100%" }} />
        )}
      </Stack>
    </Paper>
  );
}
