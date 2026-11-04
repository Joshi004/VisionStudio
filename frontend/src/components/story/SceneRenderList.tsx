import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Collapse,
  Group,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useSceneRenders,
  type SceneRender,
  type SceneRenderState,
} from "../../api/sceneRenders";
import { formatBytes, formatDateTime } from "../../format";

const STATUS: Record<SceneRender["status"], { label: string; color: string }> =
  {
    current: { label: "Current", color: "green" },
    out_of_date: { label: "Out of date", color: "yellow" },
  };

/** "4.25 s, 102 frames, 1280x720, 1.2 MB, with sound, 1 placeholder". */
function renderText(render: SceneRender): string {
  const parts: string[] = [];
  if (render.duration_s !== null) {
    parts.push(`${render.duration_s.toFixed(2)} s`);
  }
  if (render.frame_count !== null) {
    parts.push(`${render.frame_count} frames`);
  }
  if (render.width !== null && render.height !== null) {
    parts.push(`${render.width}x${render.height}`);
  }
  parts.push(formatBytes(render.size_bytes));
  parts.push(render.has_audio ? "with sound" : "no sound");
  if (render.placeholders > 0) {
    parts.push(
      `${render.placeholders} ${render.placeholders === 1 ? "placeholder" : "placeholders"}`,
    );
  }
  parts.push(render.music !== null ? "with music" : "no music");
  return parts.join(", ");
}

/** What the next render of a scene would be, as one sentence, or null when it cannot be made. */
function nextRenderText(scene: SceneRenderState): string | null {
  if (!scene.can_render || scene.planned_seconds === null) {
    return null;
  }
  const parts = [
    `The next render will be ${scene.planned_seconds.toFixed(2)} s`,
  ];
  if (scene.placeholders > 0) {
    parts.push(
      `with ${scene.placeholders} ${scene.placeholders === 1 ? "placeholder" : "placeholders"} for shots without a clip`,
    );
  }
  parts.push(
    scene.music_placement_version === null
      ? "without music"
      : `with the music of placement version ${scene.music_placement_version}`,
  );
  return `${parts.join(", ")}.`;
}

/** A badge for a scene's row: a render is being made, or how its newest render stands. */
export function SceneRenderStatus({ scene }: { scene: SceneRenderState }) {
  if (isJobActive(scene.job)) {
    return (
      <Badge variant="light" color="blue">
        Rendering scene
      </Badge>
    );
  }
  const newest = scene.renders[0];
  if (newest === undefined) {
    return null;
  }
  return (
    <Badge variant="light" color={STATUS[newest.status].color}>
      Scene video {STATUS[newest.status].label.toLowerCase()}
    </Badge>
  );
}

type SceneVideoProps = {
  scene: SceneRenderState;
};

/**
 * The newest render of one scene, played, with why it is out of date, what it warned about and
 * whether the next render would have music. Shown inside the scene's own row and in the list of
 * scene renders.
 */
export function SceneVideo({ scene }: SceneVideoProps) {
  const newest = scene.renders[0] ?? null;
  const next = nextRenderText(scene);
  return (
    <Stack gap={4}>
      {newest !== null && (
        <>
          <video
            key={newest.id}
            src={newest.url}
            controls
            preload="metadata"
            style={{ maxWidth: 480, width: "100%" }}
          />
          <Group gap="xs">
            <Badge variant="outline" color="gray">
              Scene render {newest.render_number}
            </Badge>
            <Badge variant="light" color={STATUS[newest.status].color}>
              {STATUS[newest.status].label}
            </Badge>
            <Text size="xs" c="dimmed">
              {renderText(newest)}
            </Text>
            <Anchor href={newest.url} download size="xs">
              Download
            </Anchor>
          </Group>
          {newest.reasons.map((text) => (
            <Text key={text} size="xs" c="yellow.8">
              {text}
            </Text>
          ))}
          {newest.warnings.map((warning) => (
            <Text
              key={`${warning.shot_id}/${warning.code}/${warning.message}`}
              size="xs"
              c="yellow.8"
            >
              {warning.message}
            </Text>
          ))}
        </>
      )}
      {next !== null && (
        <Text size="xs" c="dimmed">
          {next}
        </Text>
      )}
      {scene.can_render && scene.no_music_reason !== null && (
        <Text size="xs" c="dimmed">
          No music in the next render: {scene.no_music_reason}
        </Text>
      )}
      {scene.job?.status === "failed" && (
        <Alert color="red" title="The last scene render failed">
          {scene.job.error ?? "The job failed."}
        </Alert>
      )}
    </Stack>
  );
}

function SceneRenderRow({ scene }: { scene: SceneRenderState }) {
  const [showAll, setShowAll] = useState(false);
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Badge variant="outline" color="gray" style={{ textTransform: "none" }}>
          {scene.index}
        </Badge>
        <Text size="sm" fw={500}>
          {scene.title}
        </Text>
        <Text size="xs" c="dimmed">
          {scene.renders.length}{" "}
          {scene.renders.length === 1 ? "render" : "renders"}
        </Text>
        {scene.renders.length > 1 && (
          <Button
            size="compact-xs"
            variant="default"
            onClick={() => setShowAll((value) => !value)}
          >
            {showAll ? "Hide the older renders" : "Show the older renders"}
          </Button>
        )}
      </Group>
      <SceneVideo scene={scene} />
      <Collapse expanded={showAll}>
        <Stack gap={4} pt={4}>
          {scene.renders.slice(1).map((render) => (
            <Stack key={render.id} gap={0}>
              <Group gap="xs">
                <Badge variant="outline" color="gray">
                  Scene render {render.render_number}
                </Badge>
                <Badge variant="light" color={STATUS[render.status].color}>
                  {STATUS[render.status].label}
                </Badge>
                <Text size="xs" c="dimmed">
                  {formatDateTime(render.created_at)}, {renderText(render)}
                </Text>
                <Anchor href={render.url} download size="xs">
                  Download
                </Anchor>
              </Group>
              {render.reasons.map((text) => (
                <Text key={text} size="xs" c="yellow.8">
                  {text}
                </Text>
              ))}
            </Stack>
          ))}
        </Stack>
      </Collapse>
    </Stack>
  );
}

type SceneRenderListProps = {
  projectId: number;
};

/**
 * The scene renders of a project: each scene that has one, with its newest render played and the
 * older ones in a list. A scene render is started from the scene's own row in the shot generation
 * panel. It is not the final video: the full render above is.
 */
export function SceneRenderList({ projectId }: SceneRenderListProps) {
  const { data, isError, error } = useSceneRenders(projectId);
  const scenes = (data?.scenes ?? []).filter(
    (scene) => scene.renders.length > 0,
  );
  if (isError) {
    return (
      <Alert color="red" title="Could not load the scene videos">
        {describeError(error)}
      </Alert>
    );
  }
  if (scenes.length === 0) {
    return null;
  }
  return (
    <Stack gap="sm">
      <Text size="sm" fw={500}>
        Scene renders
      </Text>
      {scenes.map((scene) => (
        <SceneRenderRow key={scene.scene_id} scene={scene} />
      ))}
    </Stack>
  );
}
