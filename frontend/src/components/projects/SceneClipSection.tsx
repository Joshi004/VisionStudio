import { Alert, Badge, Button, Group, Paper, Stack, Switch, Text } from "@mantine/core";

import { useGenerateClip, useSelectTake, useSetClipSound } from "../../api/clips";
import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import type { Scene } from "../../api/scenes";
import { JobActions } from "../jobs/JobActions";
import { elapsedText, typicalText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { generateLabel, hasActiveClipJob, takeLine } from "./clipView";

type SceneClipSectionProps = {
  project: ProjectDetail;
  scene: Scene;
  /** Milliseconds since 1970 as of the last load, for the elapsed time (no timer). */
  now: number;
};

/**
 * A scene's clip: Generate or Regenerate, the status of the newest job, the clip sound
 * switch, and every take with its own player (with sound) and Use this take.
 */
export function SceneClipSection({ project, scene, now }: SceneClipSectionProps) {
  const generate = useGenerateClip(project.id);
  const selectTake = useSelectTake(project.id);
  const setSound = useSetClipSound(project.id);

  const job = scene.clip_job;
  const active = hasActiveClipJob(scene);
  const blocked = scene.generate_blocked_reason;
  const typical = typicalText(scene.clip_typical_run_seconds);

  return (
    <Stack gap="sm">
      <Text size="sm" fw={600}>
        Clip
      </Text>

      <Group gap="sm" align="center">
        <Button
          onClick={() => generate.mutate({ sceneId: scene.id })}
          loading={generate.isPending}
          disabled={blocked !== null}
        >
          {generateLabel(scene)}
        </Button>
        {blocked !== null && (
          <Text size="xs" c="dimmed" style={{ flex: 1 }}>
            {blocked}
          </Text>
        )}
      </Group>
      {blocked === null && (
        <Text size="xs" c="dimmed">
          A clip takes about {scene.target_frames} frames ({project.fps} fps) and 5 to 10 minutes
          on the GPU server. Each press makes a new take with a new random seed. Press Refresh to
          see progress.
        </Text>
      )}

      {generate.isError && (
        <Alert color="red" title="The clip was not started">
          {describeError(generate.error)}
        </Alert>
      )}

      {job !== null && (
        <Stack gap={4}>
          <Group gap="sm">
            <JobStatusBadge job={job} />
            <Text size="sm" c="dimmed">
              {elapsedText(job, now)}
              {active && typical !== "" ? ` · ${typical}` : ""}
            </Text>
            <JobActions job={job} />
          </Group>
          {job.attempt > 1 && (
            <Text size="xs" c="dimmed">
              Attempt {job.attempt}: the same request was sent again.
            </Text>
          )}
        </Stack>
      )}
      {job?.status === "failed" && job.error && (
        <Alert color="red" title="The clip failed">
          <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {job.error}
          </Text>
        </Alert>
      )}

      <Switch
        label="Use this scene's own clip sound in the final video"
        description={
          project.clip_sound_volume > 0
            ? `Mixed quietly under the voiceover, at ${Math.round(project.clip_sound_volume * 100)}% (Project settings).`
            : "The project's clip sound volume is 0, so no clip sound is used."
        }
        checked={scene.use_clip_sound}
        disabled={setSound.isPending}
        onChange={(event) =>
          setSound.mutate({ sceneId: scene.id, useClipSound: event.currentTarget.checked })
        }
      />
      {setSound.isError && (
        <Alert color="red" title="The clip sound was not changed">
          {describeError(setSound.error)}
        </Alert>
      )}

      {scene.takes.length === 0 ? (
        <Text size="sm" c="dimmed">
          No clip yet.
        </Text>
      ) : (
        <Stack gap="sm">
          {selectTake.isError && (
            <Alert color="red" title="The take was not selected">
              {describeError(selectTake.error)}
            </Alert>
          )}
          {scene.takes.map((take, index) => (
            <Paper key={take.asset_id} withBorder p="xs" radius="md">
              <Stack gap={6}>
                <Group justify="space-between">
                  <Text size="sm" fw={600}>
                    Take {scene.takes.length - index}
                  </Text>
                  {take.selected ? (
                    <Badge color="green" variant="light">
                      Used in the final video
                    </Badge>
                  ) : (
                    <Button
                      size="compact-xs"
                      variant="default"
                      loading={
                        selectTake.isPending && selectTake.variables?.assetId === take.asset_id
                      }
                      onClick={() =>
                        selectTake.mutate({ sceneId: scene.id, assetId: take.asset_id })
                      }
                    >
                      Use this take
                    </Button>
                  )}
                </Group>
                {/* Keyed by the file, so another take always loads fresh. */}
                <video
                  key={take.asset_id}
                  src={take.url}
                  controls
                  preload="metadata"
                  playsInline
                  style={{ width: "100%", maxHeight: 440, background: "#000" }}
                />
                <Text size="xs" c="dimmed">
                  {takeLine(take)}
                </Text>
                {take.out_of_date && (
                  <Text size="xs" c="orange.8">
                    The scene's cuts changed after this take was made, so it no longer matches
                    the voiceover.
                  </Text>
                )}
                {take.too_short && (
                  <Text size="xs" c="orange.8">
                    This take has fewer frames than the scene needs now ({scene.target_frames}).
                  </Text>
                )}
              </Stack>
            </Paper>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
