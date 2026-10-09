import { useState } from "react";
import { Alert, Badge, Button, Group, Paper, Select, Stack, Switch, Text } from "@mantine/core";

import {
  useGenerateClip,
  useSelectTake,
  useSetClipSound,
  useSetSceneVideoModel,
} from "../../api/clips";
import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import type { Scene } from "../../api/scenes";
import { JobActions } from "../jobs/JobActions";
import { elapsedText, typicalText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import {
  INHERIT,
  VIDEO_MODELS,
  isVideoModel,
  modelChoices,
  videoModelLabel,
  type VideoModel,
} from "../../videoModels";
import { generateLabel, hasActiveClipJob, modelSourceText, takeLine } from "./clipView";

type SceneClipSectionProps = {
  project: ProjectDetail;
  scene: Scene;
  /** The current time in milliseconds since 1970, for the elapsed time. */
  now: number;
};

/**
 * A scene's clip: Generate or Regenerate (with the video model for that one take), the status
 * of the newest job, the scene's own video model, the clip sound switch, and every take with
 * its model, its own player (with sound) and Use this take.
 */
export function SceneClipSection({ project, scene, now }: SceneClipSectionProps) {
  const generate = useGenerateClip(project.id);
  const selectTake = useSelectTake(project.id);
  const setSound = useSetClipSound(project.id);
  const setModel = useSetSceneVideoModel(project.id);
  // The model picked for the next take only. Null: the scene's effective model.
  const [override, setOverride] = useState<VideoModel | null>(null);

  const chosenModel = override ?? scene.effective_video_model;
  const chosenNote: string | undefined = scene.video_model_notes[chosenModel];
  const projectModel = project.video_model ?? project.default_video_model;

  const job = scene.clip_job;
  const active = hasActiveClipJob(scene);
  const blocked = scene.generate_blocked_reason;
  const typical = typicalText(scene.clip_typical_run_seconds);

  return (
    <Stack gap="sm">
      <Text size="sm" fw={600}>
        Clip
      </Text>

      <Group gap="sm" align="flex-end">
        <Select
          label="Model for this take"
          size="xs"
          data={VIDEO_MODELS}
          value={chosenModel}
          onChange={(value) =>
            setOverride(
              isVideoModel(value) && value !== scene.effective_video_model ? value : null,
            )
          }
          allowDeselect={false}
          disabled={blocked !== null}
          w={130}
        />
        <Button
          onClick={() =>
            generate.mutate(
              { sceneId: scene.id, videoModel: override ?? undefined },
              { onSuccess: () => setOverride(null) },
            )
          }
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
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            Made with {videoModelLabel(chosenModel)} (
            {override !== null
              ? "this take only"
              : modelSourceText(scene.effective_video_model_source)}
            ). A clip takes about {scene.target_frames} frames ({project.fps} fps) and 5 to 10
            minutes on the GPU server. Each press makes a new take with a new random seed. The
            page updates by itself.
          </Text>
          {chosenNote !== undefined && (
            <Text size="xs" c="orange.8">
              {chosenNote}
            </Text>
          )}
        </Stack>
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

      <Select
        label="Video model for this scene"
        description="Used by Generate and Regenerate unless you pick another model for one take. Clips already made keep the model they were made with."
        data={modelChoices(`Project default (${videoModelLabel(projectModel)})`)}
        value={scene.video_model ?? INHERIT}
        onChange={(value) =>
          value !== null &&
          setModel.mutate({ sceneId: scene.id, videoModel: isVideoModel(value) ? value : null })
        }
        allowDeselect={false}
        disabled={setModel.isPending}
        maw={360}
      />
      {setModel.isError && (
        <Alert color="red" title="The video model was not changed">
          {describeError(setModel.error)}
        </Alert>
      )}

      <Switch
        label="Use this scene's own clip sound in the final video"
        description={
          project.clip_sound_volume > 0
            ? `Mixed under the voiceover at ${Math.round(project.clip_sound_volume * 100)}% of its level (Project settings).`
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
                  <Group gap="xs">
                    <Text size="sm" fw={600}>
                      Take {scene.takes.length - index}
                    </Text>
                    {take.video_model !== null && (
                      <Badge
                        variant="light"
                        color={take.video_model === "ltx-2.5" ? "blue" : "gray"}
                      >
                        {videoModelLabel(take.video_model)}
                      </Badge>
                    )}
                  </Group>
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
                {take.model_note !== null && (
                  <Text size="xs" c="orange.8">
                    {take.model_note}
                  </Text>
                )}
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
