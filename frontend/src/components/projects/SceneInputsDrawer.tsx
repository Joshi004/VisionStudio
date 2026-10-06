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
import { DESCRIPTION_MAX_CHARS, useSaveDescription } from "../../api/sceneInputs";
import type { Scene } from "../../api/scenes";
import { FrameSlot } from "./FrameSlot";
import { countWords, missingText, promptHints } from "./promptHints";
import { SceneClipSection } from "./SceneClipSection";
import { seconds } from "./sceneView";

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
  const save = useSaveDescription(project.id);
  // What the user has typed and not saved yet. It only counts for the scene it was typed in.
  const [edit, setEdit] = useState<{ sceneId: number; text: string } | null>(null);

  const position = scenes.findIndex((scene) => scene.id === sceneId);
  const scene = position >= 0 ? scenes[position] : undefined;
  const previous = position > 0 ? scenes[position - 1] : undefined;
  const next = position >= 0 && position < scenes.length - 1 ? scenes[position + 1] : undefined;

  const saved = scene?.scene_description ?? "";
  const draft = scene !== undefined && edit?.sceneId === scene.id ? edit.text : saved;
  const dirty = scene !== undefined && draft !== saved;
  const tooLong = draft.length > DESCRIPTION_MAX_CHARS;
  const hints = promptHints(draft);

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

  function saveDescription() {
    if (scene === undefined) {
      return;
    }
    save.mutate(
      { sceneId: scene.id, description: draft },
      { onSuccess: () => setEdit(null) },
    );
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
              Save the description to move to another scene.
            </Text>
          )}

          <Stack gap="xs">
            <Textarea
              label="Description"
              description="The motion that connects the two frames: one flowing paragraph, in the present tense. Style, camera and lighting come from the project's guidelines."
              placeholder="A lighthouse beam sweeps slowly across a calm night sea..."
              value={draft}
              onChange={(event) => setEdit({ sceneId: scene.id, text: event.currentTarget.value })}
              autosize
              minRows={4}
              maxRows={14}
              error={tooLong ? `At most ${DESCRIPTION_MAX_CHARS.toLocaleString()} characters.` : undefined}
            />
            {hints.map((hint) => (
              <Text key={hint} size="xs" c="orange.8">
                {hint}
              </Text>
            ))}
            <Group justify="space-between">
              <Group gap="sm">
                <Button
                  onClick={saveDescription}
                  disabled={!dirty || tooLong}
                  loading={save.isPending}
                >
                  Save description
                </Button>
                {save.isSuccess && !dirty && (
                  <Text size="sm" c="green">
                    Saved
                  </Text>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                {countWords(draft)} words
              </Text>
            </Group>
            {save.isError && (
              <Alert color="red" title="The description was not saved">
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
