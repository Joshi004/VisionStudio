import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Divider,
  Drawer,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import {
  DESCRIPTION_MAX_CHARS,
  useSaveSceneTexts,
  type SceneTexts,
} from "../../api/sceneInputs";
import type { Scene } from "../../api/scenes";
import { FrameSlot } from "./FrameSlot";
import { countWords, missingText, promptHints } from "./promptHints";
import { SceneClipSection } from "./SceneClipSection";
import { seconds } from "./sceneView";

type TextKey = keyof SceneTexts;
const TEXT_KEYS: TextKey[] = [
  "scene_description",
  "first_frame_description",
  "last_frame_description",
];

/** Who wrote a text, and whether the box holds changes that are not saved yet. */
function SourceBadge({ source, edited }: { source: Scene["scene_description_source"]; edited: boolean }) {
  if (edited) {
    return (
      <Badge color="yellow" variant="light">
        Edited, not saved
      </Badge>
    );
  }
  if (source === "ai") {
    return (
      <Badge color="grape" variant="light">
        AI draft
      </Badge>
    );
  }
  if (source === "manual") {
    return (
      <Badge color="gray" variant="light">
        Written by you
      </Badge>
    );
  }
  return null;
}

type SceneInputsDrawerProps = {
  project: ProjectDetail;
  scenes: Scene[];
  /** The scene being edited. The drawer is closed when this is null or the scene is gone. */
  sceneId: number | null;
  /** Milliseconds since 1970 as of the last load, for the clip job's elapsed time. */
  now: number;
  onSelect: (sceneId: number) => void;
  onClose: () => void;
};

/**
 * Everything a scene needs before a clip can be made (its description, the prompt that will
 * be sent, and its first and last frame), and then the clip itself: Generate, the status of
 * the job and the takes. It reads the scene from the scenes query, so it shows the new state
 * after every save without another request.
 */
export function SceneInputsDrawer({
  project,
  scenes,
  sceneId,
  now,
  onSelect,
  onClose,
}: SceneInputsDrawerProps) {
  const save = useSaveSceneTexts(project.id);
  // What the user has typed and not saved yet. It only counts for the scene it was typed in.
  const [edit, setEdit] = useState<{ sceneId: number; texts: SceneTexts } | null>(null);

  const position = scenes.findIndex((scene) => scene.id === sceneId);
  const scene = position >= 0 ? scenes[position] : undefined;
  const previous = position > 0 ? scenes[position - 1] : undefined;
  const next = position >= 0 && position < scenes.length - 1 ? scenes[position + 1] : undefined;

  const saved: Record<TextKey, string> = {
    scene_description: scene?.scene_description ?? "",
    first_frame_description: scene?.first_frame_description ?? "",
    last_frame_description: scene?.last_frame_description ?? "",
  };
  const typed = scene !== undefined && edit?.sceneId === scene.id ? edit.texts : {};
  const draftOf = (key: TextKey) => typed[key] ?? saved[key];
  const changed = scene === undefined ? [] : TEXT_KEYS.filter((key) => draftOf(key) !== saved[key]);
  const dirty = changed.length > 0;
  const tooLong = TEXT_KEYS.some((key) => draftOf(key).length > DESCRIPTION_MAX_CHARS);
  const draft = draftOf("scene_description");
  const hints = promptHints(draft);

  function type(key: TextKey, text: string) {
    if (scene !== undefined) {
      setEdit({ sceneId: scene.id, texts: { ...typed, [key]: text } });
    }
  }

  function select(target: Scene) {
    setEdit(null);
    save.reset();
    onSelect(target.id);
  }

  function close() {
    setEdit(null);
    save.reset();
    onClose();
  }

  function saveTexts() {
    if (scene === undefined) {
      return;
    }
    const texts: SceneTexts = {};
    for (const key of changed) {
      texts[key] = draftOf(key);
    }
    save.mutate({ sceneId: scene.id, texts }, { onSuccess: () => setEdit(null) });
  }

  return (
    <Drawer
      opened={scene !== undefined}
      onClose={close}
      position="right"
      size="lg"
      // Typed text is not lost by a stray click or key.
      closeOnClickOutside={!dirty}
      closeOnEscape={!dirty}
      title={
        scene !== undefined ? (
          <Title order={4} component="span">
            Scene {scene.index + 1} · {seconds(scene.start_s)} – {seconds(scene.end_s)} s
          </Title>
        ) : null
      }
    >
      {scene !== undefined && (
        <Stack gap="md">
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <Stack gap={4}>
              <Group gap="xs">
                {scene.ready ? (
                  <Badge color="green" variant="light">
                    Ready
                  </Badge>
                ) : (
                  <Badge color="gray" variant="light">
                    Not ready
                  </Badge>
                )}
                {!scene.ready && (
                  <Text size="sm" c="dimmed">
                    Needs: {missingText(scene.missing)}
                  </Text>
                )}
              </Group>
              <Text size="sm" c="dimmed">
                {scene.text}
              </Text>
            </Stack>
            <Group gap="xs" wrap="nowrap">
              <Button
                size="compact-sm"
                variant="default"
                disabled={previous === undefined || dirty}
                onClick={() => previous && select(previous)}
              >
                Previous
              </Button>
              <Button
                size="compact-sm"
                variant="default"
                disabled={next === undefined || dirty}
                onClick={() => next && select(next)}
              >
                Next
              </Button>
            </Group>
          </Group>
          {dirty && (
            <Text size="xs" c="dimmed">
              Save your changes to move to another scene.
            </Text>
          )}

          <Stack gap="xs">
            <Textarea
              label={
                <Group gap="xs">
                  <span>Description</span>
                  <SourceBadge
                    source={scene.scene_description_source}
                    edited={changed.includes("scene_description")}
                  />
                </Group>
              }
              description="The motion that connects the two frames: one flowing paragraph, in the present tense. Style, camera and lighting come from the project's guidelines."
              placeholder="A lighthouse beam sweeps slowly across a calm night sea..."
              value={draft}
              onChange={(event) => type("scene_description", event.currentTarget.value)}
              autosize
              minRows={4}
              maxRows={14}
              error={
                draftOf("scene_description").length > DESCRIPTION_MAX_CHARS
                  ? `At most ${DESCRIPTION_MAX_CHARS.toLocaleString()} characters.`
                  : undefined
              }
            />
            {hints.map((hint) => (
              <Text key={hint} size="xs" c="orange.8">
                {hint}
              </Text>
            ))}
            <Text size="xs" c="dimmed" ta="right">
              {countWords(draft)} words
            </Text>

            <Textarea
              label={
                <Group gap="xs">
                  <span>First frame description</span>
                  <SourceBadge
                    source={scene.frame_descriptions_source}
                    edited={changed.includes("first_frame_description")}
                  />
                </Group>
              }
              description="What the first frame shows: a guide for making or choosing the frame. An AI draft is written from the script only, so check that it matches your frame."
              value={draftOf("first_frame_description")}
              onChange={(event) => type("first_frame_description", event.currentTarget.value)}
              autosize
              minRows={3}
              maxRows={10}
              error={
                draftOf("first_frame_description").length > DESCRIPTION_MAX_CHARS
                  ? `At most ${DESCRIPTION_MAX_CHARS.toLocaleString()} characters.`
                  : undefined
              }
            />
            <Textarea
              label={
                <Group gap="xs">
                  <span>Last frame description</span>
                  <SourceBadge
                    source={scene.frame_descriptions_source}
                    edited={changed.includes("last_frame_description")}
                  />
                </Group>
              }
              description="What the last frame shows: the same shot after the change that happens in this scene."
              value={draftOf("last_frame_description")}
              onChange={(event) => type("last_frame_description", event.currentTarget.value)}
              autosize
              minRows={3}
              maxRows={10}
              error={
                draftOf("last_frame_description").length > DESCRIPTION_MAX_CHARS
                  ? `At most ${DESCRIPTION_MAX_CHARS.toLocaleString()} characters.`
                  : undefined
              }
            />

            <Group gap="sm">
              <Button onClick={saveTexts} disabled={!dirty || tooLong} loading={save.isPending}>
                Save
              </Button>
              {save.isSuccess && !dirty && (
                <Text size="sm" c="green">
                  Saved
                </Text>
              )}
            </Group>
            {scene.description_job_id !== null && (
              <Text size="xs" c="dimmed">
                Some of this text was drafted by the AI in job {scene.description_job_id}. Its exact
                request and answer are on the{" "}
                <Anchor component={Link} to="/activity" size="xs">
                  Activity page
                </Anchor>
                .
              </Text>
            )}
            {save.isError && (
              <Alert color="red" title="The text was not saved">
                {describeError(save.error)}
              </Alert>
            )}
          </Stack>

          <Stack gap={6}>
            <Text size="sm" fw={600}>
              Prompt sent to the video model
            </Text>
            <Paper withBorder p="xs" radius="md">
              {scene.prompt !== null ? (
                <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {scene.prompt}
                </Text>
              ) : (
                <Text size="sm" c="dimmed">
                  Save a description to see the prompt.
                </Text>
              )}
            </Paper>
            {dirty && (
              <Text size="xs" c="dimmed">
                Save to update the prompt.
              </Text>
            )}
            <Text size="xs" c="dimmed">
              Built from the style prefix, the description and the prompt suffix.
              {project.negative_prompt ? (
                <> Negative prompt: {project.negative_prompt}</>
              ) : (
                <> No negative prompt is set.</>
              )}{" "}
              <Anchor component={Link} to={`/projects/${project.id}/settings`} size="xs">
                Project settings
              </Anchor>
            </Text>
          </Stack>

          <Stack gap={6}>
            <Text size="sm" c="dimmed">
              Frames are cropped from the centre and resized to {project.gen_width} x{" "}
              {project.gen_height} for the video model. The previews show exactly that.
            </Text>
            <SimpleGrid cols={2} spacing="md">
              <FrameSlot
                key={`${scene.id}-first`}
                project={project}
                sceneId={scene.id}
                slot="first"
                frame={scene.first_frame}
                label="First frame"
              />
              <FrameSlot
                key={`${scene.id}-last`}
                project={project}
                sceneId={scene.id}
                slot="last"
                frame={scene.last_frame}
                label="Last frame"
              />
            </SimpleGrid>
          </Stack>

          <Divider />
          <SceneClipSection project={project} scene={scene} now={now} />
        </Stack>
      )}
    </Drawer>
  );
}
