import { Alert, Button, Group, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  isPreviewOf,
  useMusicPreview,
  useStartMusicPreview,
  type MusicPreviewTarget,
} from "../../api/musicPreview";
import { isJobActive } from "../../api/polling";
import { formatSeconds } from "./musicPlanView";

type MusicPreviewPlayerProps = {
  projectId: number;
  /** What to hear: a scene, or a cue (with a take to hear instead of the selected one). */
  target: MusicPreviewTarget;
  /** The button's text. */
  label?: string;
};

/**
 * "Hear it in context": a button that makes a short sound-only mix of the story (the clips' sound,
 * the narration and the music, at the render's loudness) for a scene or a cue, and a player for
 * it. The project keeps one newest preview, so the player shows only while the newest preview is
 * of this target; asking for another replaces it. Nothing is paid for.
 */
export function MusicPreviewPlayer({
  projectId,
  target,
  label = "Hear it in context",
}: MusicPreviewPlayerProps) {
  const { data: preview } = useMusicPreview(projectId);
  const start = useStartMusicPreview(projectId);

  const mine = preview && isPreviewOf(preview, target) ? preview : null;
  const working = start.isPending || isJobActive(mine ? { status: mine.status } : null);

  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Button
          variant="default"
          size="xs"
          loading={working}
          onClick={() => start.mutate(target)}
        >
          {label}
        </Button>
        {mine !== null && working && mine.phase !== null && (
          <Text size="xs" c="dimmed">
            {mine.phase}
          </Text>
        )}
      </Group>
      {start.isError && (
        <Alert color="red" title="Could not start the preview">
          {describeError(start.error)}
        </Alert>
      )}
      {mine?.status === "failed" && !start.isPending && (
        <Alert color="red" title="The preview failed">
          {mine.error ?? "The job failed."}
        </Alert>
      )}
      {mine?.status === "succeeded" && mine.url !== null && (
        <Stack gap={2}>
          <audio controls preload="metadata" src={mine.url} style={{ width: "100%" }} />
          {mine.window_start_s !== null && mine.window_end_s !== null && (
            <Text size="xs" c="dimmed">
              {formatSeconds(mine.window_start_s)} to {formatSeconds(mine.window_end_s)} of the
              story. Press again after a change to hear the new mix.
            </Text>
          )}
        </Stack>
      )}
    </Stack>
  );
}
